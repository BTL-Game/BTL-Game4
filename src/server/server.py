"""Dedicated multi-room TCP server for Custom UNO Online.

Threading model:
- 1 accept thread (main): waits for new client connections.
- 1 reader thread per connected client: parses JSON envelopes, dispatches under
  a single global lock to keep engine state mutations serialized.
- 1 tick thread (1 Hz): drives reaction-event timeouts, disconnect FSM,
  empty-room garbage collection. Broadcasts state on every tick.

Per-room garbage collection:
- A room is removed when it has no connected players for >= ROOM_GC_AFTER_SEC.

Wire protocol: see NETWORK_PLAN.md §3.
"""
from __future__ import annotations

import json
import random
import socket
import string
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from src.core.actions import LeaveRoom, AddBot, DrawCard
from src.core.engine import GameEngine
from src.core.modes import MODE_BASIC, MODE_ASIAN, VALID_MODES
from src.core.game_state import to_view
from src.network.codec import action_from_json, view_to_json
from src.ai.simple_bot import SimpleBot


ROOM_GC_AFTER_SEC = 10.0
TICK_HZ = 4.0  # 4 ticks per second; tight enough for 30s/60s timers + reaction.
HEARTBEAT_TIMEOUT_SEC = 15.0  # close conn after no PING/data for this long.
ROOM_CODE_LEN = 8

# --- abuse limits for online deployment ---------------------------------------
MAX_LINE_BYTES = 8 * 1024            # drop a connection sending >8KB w/o newline
MAX_NAME_LEN = 20
MAX_CHAT_LEN = 200
MAX_CHAT_PER_10S = 30                # per-conn chat rate (relaxed for class demo)
MAX_MSG_PER_SEC = 60                 # per-conn overall message rate (token bucket)
# Per-IP cap protects against a single host opening unbounded sockets, but
# classmates often share a NAT/dorm gateway, so keep it generous. Total cap
# is just a sanity ceiling so a runaway client can't exhaust the FD table.
MAX_CONNS_PER_IP = 64
MAX_TOTAL_CONNS = 1024
MAX_ROOMS = 200
NAME_ALLOWED = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _-.[]"
)


def _sanitize_name(raw: object) -> str:
    """Coerce user-supplied name to a printable, length-bounded string."""
    if not isinstance(raw, str):
        return ""
    cleaned = "".join(ch for ch in raw if ch in NAME_ALLOWED).strip()
    return cleaned[:MAX_NAME_LEN]


def _sanitize_chat(raw: object) -> str:
    if not isinstance(raw, str):
        return ""
    # keep printable chars, drop control bytes (newlines etc).
    cleaned = "".join(ch for ch in raw if ch.isprintable()).strip()
    return cleaned[:MAX_CHAT_LEN]


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------
@dataclass(eq=False)
class Connection:
    sock: socket.socket
    addr: tuple[str, int]
    player_id: str | None = None
    room_code: str | None = None
    name: str = ""
    closed: bool = False
    last_seen: float = field(default_factory=time.monotonic)
    # Token bucket for overall message rate.
    _bucket: float = field(default=float(MAX_MSG_PER_SEC))
    _bucket_at: float = field(default_factory=time.monotonic)
    # Sliding chat-rate window timestamps.
    _chat_times: list[float] = field(default_factory=list)

    def allow_message(self) -> bool:
        now = time.monotonic()
        elapsed = now - self._bucket_at
        self._bucket_at = now
        self._bucket = min(
            float(MAX_MSG_PER_SEC),
            self._bucket + elapsed * MAX_MSG_PER_SEC,
        )
        if self._bucket < 1.0:
            return False
        self._bucket -= 1.0
        return True

    def allow_chat(self) -> bool:
        now = time.monotonic()
        self._chat_times = [t for t in self._chat_times if now - t < 10.0]
        if len(self._chat_times) >= MAX_CHAT_PER_10S:
            return False
        self._chat_times.append(now)
        return True

    def send_envelope(self, msg_type: str, payload: dict[str, Any] | None = None) -> None:
        if self.closed:
            return
        env = {"type": msg_type, "payload": payload or {}}
        try:
            self.sock.sendall((json.dumps(env) + "\n").encode("utf-8"))
        except OSError:
            self.closed = True

    def close(self) -> None:
        self.closed = True
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Room
# ---------------------------------------------------------------------------
@dataclass
class Room:
    code: str
    engine: GameEngine
    connections: dict[str, Connection] = field(default_factory=dict)  # player_id -> conn
    bots: dict[str, SimpleBot] = field(default_factory=dict)
    bot_ready_at: dict[tuple[str, str], float] = field(default_factory=dict)
    empty_since: float | None = None

    @property
    def host_name(self) -> str:
        for p in self.engine.state.players:
            if p.is_host:
                return p.name
        return "?"

    @property
    def n_players(self) -> int:
        return len(self.engine.state.players)

    @property
    def started(self) -> bool:
        return self.engine.state.started

    @property
    def visible(self) -> bool:
        return (not self.started) and self.n_players < 4

    def to_summary(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "host_name": self.host_name,
            "n_players": self.n_players,
            "max_players": 4,
            "started": self.started,
            "mode": self.engine.state.mode,
        }

    def broadcast_state(self) -> None:
        for pid, conn in list(self.connections.items()):
            if conn.closed:
                continue
            view = to_view(self.engine.state, pid, self.engine.log)
            conn.send_envelope("STATE", view_to_json(view))

    def broadcast_event(self, kind: str, **fields: Any) -> None:
        payload = {"kind": kind, **fields}
        for conn in list(self.connections.values()):
            if conn.closed:
                continue
            conn.send_envelope("EVENT", payload)

    def clear_bot_timers_for(self, player_id: str) -> None:
        for key in list(self.bot_ready_at.keys()):
            if key[0] == player_id:
                self.bot_ready_at.pop(key, None)

    def bot_delay_for_stage(self, stage: str) -> float:
        if stage == "action":
            return random.uniform(1.0, 3.0)
        if stage == "reaction":
            return random.uniform(0.6, 1.5)
        return random.uniform(0.3, 0.8)


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
class Server:
    def __init__(self, host: str = "0.0.0.0", port: int = 5555) -> None:
        self.host = host
        self.port = port
        self.lock = threading.RLock()
        self.rooms: dict[str, Room] = {}
        self.all_conns: set[Connection] = set()
        self._listen_sock: socket.socket | None = None
        self._stop = threading.Event()

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def serve_forever(self) -> None:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((self.host, self.port))
        s.listen(8)
        s.settimeout(0.5)
        self._listen_sock = s
        print(f"[server] listening on {self.host}:{self.port}")
        threading.Thread(target=self._tick_loop, name="tick", daemon=True).start()
        try:
            while not self._stop.is_set():
                try:
                    client_sock, addr = s.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                # Abuse caps: total + per-IP. Reject before spawning a thread.
                ip = addr[0]
                with self.lock:
                    if len(self.all_conns) >= MAX_TOTAL_CONNS:
                        self._reject_conn(client_sock, "server full")
                        continue
                    same_ip = sum(1 for c in self.all_conns if c.addr[0] == ip)
                    if same_ip >= MAX_CONNS_PER_IP:
                        self._reject_conn(client_sock, "too many connections from your IP")
                        continue
                conn = Connection(sock=client_sock, addr=addr)
                with self.lock:
                    self.all_conns.add(conn)
                threading.Thread(
                    target=self._reader_loop,
                    args=(conn,),
                    name=f"reader-{addr[1]}",
                    daemon=True,
                ).start()
        finally:
            s.close()
            print("[server] shut down")

    def _reject_conn(self, sock: socket.socket, reason: str) -> None:
        """Politely close an over-quota socket without joining the active set."""
        try:
            env = {"type": "ERROR", "payload": {"msg": reason}}
            sock.sendall((json.dumps(env) + "\n").encode("utf-8"))
        except OSError:
            pass
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass

    def shutdown(self) -> None:
        self._stop.set()
        if self._listen_sock is not None:
            try:
                self._listen_sock.close()
            except OSError:
                pass

    # ------------------------------------------------------------------
    # tick loop
    # ------------------------------------------------------------------
    def _tick_loop(self) -> None:
        period = 1.0 / TICK_HZ
        while not self._stop.is_set():
            time.sleep(period)
            with self.lock:
                self._tick_once()

    def _tick_once(self) -> None:
        now = time.monotonic()
        # Heartbeat sweep: close any connection silent for too long. The TCP
        # close in turn fires _handle_disconnect, which feeds the engine FSM.
        for conn in list(self.all_conns):
            if conn.closed:
                self.all_conns.discard(conn)
                continue
            if now - conn.last_seen > HEARTBEAT_TIMEOUT_SEC:
                print(f"[server] heartbeat timeout for {conn.name or conn.addr}")
                conn.close()  # reader loop will catch and call _handle_disconnect
        dead: list[str] = []
        for code, room in self.rooms.items():
            before_players = {p.player_id: p.name for p in room.engine.state.players}
            before_host = next(
                (p.player_id for p in room.engine.state.players if p.is_host), None
            )
            before_reaction = room.engine.state.reaction_event.active
            before_ended = room.engine.state.ended
            room.engine.tick()

            cur_id = room.engine.state.current_player_id()
            if cur_id is not None and cur_id in room.bots and not room.engine.state.ended:
                if room.engine.state.reaction_event.active:
                    stage = "reaction"
                elif room.engine.state.awaiting_color_for_player == cur_id:
                    stage = "color"
                elif room.engine.state.awaiting_direction_for_player == cur_id:
                    stage = "direction"
                elif room.engine.state.awaiting_target_for_player == cur_id:
                    stage = "target"
                else:
                    stage = "action"
                ready_key = (cur_id, stage)
                ready_at = room.bot_ready_at.get(ready_key)
                if ready_at is None:
                    room.bot_ready_at[ready_key] = now + room.bot_delay_for_stage(stage)
                elif now >= ready_at:
                    bot = room.bots[cur_id]
                    view = to_view(room.engine.state, cur_id, room.engine.log)
                    if stage == "reaction":
                        action = bot.reaction(view, cur_id, delay=False)
                    elif stage == "color":
                        action = bot.choose_color(view, cur_id, delay=False)
                    elif stage == "direction":
                        action = bot.choose_direction(view, cur_id, delay=False)
                    elif stage == "target":
                        action = bot.choose_target(view, cur_id, delay=False)
                    else:
                        action = bot.choose_action(view, cur_id, delay=False)
                    room.bot_ready_at.pop(ready_key, None)
                    ok, _ = room.engine.handle_action(cur_id, action)
                    if not ok:
                        # Fail-safe: avoid freezing a bot turn after special-rule states.
                        # If normal play is rejected, try drawing to force progress.
                        if stage == "action":
                            draw_ok, _ = room.engine.handle_action(cur_id, DrawCard())
                            if not draw_ok:
                                room.bot_ready_at[ready_key] = now + room.bot_delay_for_stage(stage)
                        else:
                            room.bot_ready_at[ready_key] = now + random.uniform(0.2, 0.5)

            after_player_ids = {p.player_id for p in room.engine.state.players}
            removed = set(before_players.keys()) - after_player_ids
            for pid in removed:
                conn = room.connections.pop(pid, None)
                # remove from bots mapping if needed
                if pid in room.bots:
                    room.bots.pop(pid, None)
                room.clear_bot_timers_for(pid)
                room.broadcast_event(
                    "REMOVED", player_name=before_players.get(pid, "?"),
                    reason="disconnect timeout",
                )
                if conn is not None:
                    conn.send_envelope("KICKED", {"reason": "removed by server"})
                    conn.close()
            after_host = next(
                (p.player_id for p in room.engine.state.players if p.is_host), None
            )
            if after_host and after_host != before_host:
                new_host = next(p for p in room.engine.state.players if p.is_host)
                room.broadcast_event("HOST_MIGRATED", new_host_name=new_host.name)
            after_reaction = room.engine.state.reaction_event.active
            if after_reaction and not before_reaction:
                room.broadcast_event("REACTION_START")
            if room.engine.state.ended and not before_ended and room.engine.state.winner_id:
                winner_name = next(
                    (p.name for p in room.engine.state.players
                     if p.player_id == room.engine.state.winner_id),
                    "?",
                )
                room.broadcast_event("MATCH_END", winner_name=winner_name, walkover=True)
            room.broadcast_state()
            if room.n_players == 0:
                room.empty_since = room.empty_since or now
                if now - room.empty_since >= ROOM_GC_AFTER_SEC:
                    dead.append(code)
            else:
                room.empty_since = None
        for code in dead:
            print(f"[server] GC empty room {code}")
            self.rooms.pop(code, None)

    # ------------------------------------------------------------------
    # reader loop
    # ------------------------------------------------------------------
    def _reader_loop(self, conn: Connection) -> None:
        buf = b""
        try:
            conn.sock.settimeout(None)
            while not self._stop.is_set() and not conn.closed:
                try:
                    chunk = conn.sock.recv(4096)
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
                # Hard cap on the unparsed buffer — protects against a peer
                # that streams bytes without ever sending a newline.
                if len(buf) > MAX_LINE_BYTES:
                    conn.send_envelope("ERROR", {"msg": "message too large"})
                    break
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    if len(line) > MAX_LINE_BYTES:
                        conn.send_envelope("ERROR", {"msg": "message too large"})
                        conn.closed = True
                        break
                    try:
                        env = json.loads(line.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        conn.send_envelope("ERROR", {"msg": "malformed JSON"})
                        continue
                    if not isinstance(env, dict):
                        conn.send_envelope("ERROR", {"msg": "envelope must be object"})
                        continue
                    if not conn.allow_message():
                        # Silently drop — don't echo back, since echoing under
                        # a flood would make the abuse worse.
                        continue
                    self._dispatch(conn, env)
        finally:
            self._handle_disconnect(conn)

    # ------------------------------------------------------------------
    # dispatch
    # ------------------------------------------------------------------
    def _dispatch(self, conn: Connection, env: dict[str, Any]) -> None:
        conn.last_seen = time.monotonic()
        msg_type = env.get("type")
        payload = env.get("payload") or {}
        if not isinstance(payload, dict):
            conn.send_envelope("ERROR", {"msg": "payload must be object"})
            return
        handler = {
            "LIST_ROOMS": self._on_list_rooms,
            "CREATE_ROOM": self._on_create_room,
            "JOIN_ROOM": self._on_join_room,
            "LEAVE_ROOM": self._on_leave_room,
            "ACTION": self._on_action,
            "CHAT": self._on_chat,
            "PING": self._on_ping,
            "SERVER_STATUS": self._on_server_status,
        }.get(msg_type)
        if handler is None:
            conn.send_envelope("ERROR", {"msg": f"unknown type {msg_type!r}"})
            return
        with self.lock:
            try:
                handler(conn, payload)
            except Exception as exc:  # never let one client crash the server
                conn.send_envelope("ERROR", {"msg": f"server error: {exc}"})

    def _on_ping(self, conn: Connection, payload: dict[str, Any]) -> None:
        # Coerce timestamp to a number — never echo arbitrary client data back.
        t_raw = payload.get("t", 0.0)
        try:
            t = float(t_raw) if isinstance(t_raw, (int, float, str)) else 0.0
        except (TypeError, ValueError):
            t = 0.0
        conn.send_envelope("PONG", {"t": t})

    def _on_server_status(self, conn: Connection, payload: dict[str, Any]) -> None:
        del payload
        n_players = sum(
            1 for r in self.rooms.values()
            for p in r.engine.state.players
            if p.connected and p.player_id not in r.bots
        )
        n_visible = sum(1 for r in self.rooms.values() if r.visible)
        conn.send_envelope("SERVER_STATUS", {
            "n_rooms": len(self.rooms),
            "n_visible_rooms": n_visible,
            "n_players": n_players,
            "n_connections": len(self.all_conns),
            "max_connections": MAX_TOTAL_CONNS,
        })

    def _on_list_rooms(self, conn: Connection, payload: dict[str, Any]) -> None:
        rooms = [r.to_summary() for r in self.rooms.values() if r.visible]
        conn.send_envelope("ROOM_LIST", {"rooms": rooms})

    def _gen_room_code(self) -> str:
        while True:
            code = "".join(random.choice(string.digits) for _ in range(ROOM_CODE_LEN))
            if code not in self.rooms:
                return code

    def _on_create_room(self, conn: Connection, payload: dict[str, Any]) -> None:
        if conn.player_id is not None:
            conn.send_envelope("ERROR", {"msg": "already in a room"})
            return
        if len(self.rooms) >= MAX_ROOMS:
            conn.send_envelope("ERROR", {"msg": "server room limit reached"})
            return
        name = _sanitize_name(payload.get("name")) or "Player"
        mode_raw = payload.get("mode", MODE_BASIC)
        mode = mode_raw if isinstance(mode_raw, str) else MODE_BASIC
        if mode not in VALID_MODES:
            mode = MODE_BASIC
        host_id = uuid4().hex[:8]
        engine = GameEngine()
        engine.create_room(host_id, name, mode=mode)
        # Override the engine's auto-generated code with one unique to this server.
        code = self._gen_room_code()
        engine.state.room_code = code
        room = Room(code=code, engine=engine)
        room.connections[host_id] = conn
        conn.player_id = host_id
        conn.room_code = code
        conn.name = name
        self.rooms[code] = room
        conn.send_envelope("JOINED", {
            "room_code": code,
            "player_id": host_id,
            "is_host": True,
        })
        room.broadcast_state()
        print(f"[server] room {code} created by {name}")

    def _on_join_room(self, conn: Connection, payload: dict[str, Any]) -> None:
        if conn.player_id is not None:
            conn.send_envelope("ERROR", {"msg": "already in a room"})
            return
        code_raw = payload.get("code", "")
        code = code_raw.strip() if isinstance(code_raw, str) else ""
        if not (code.isdigit() and len(code) == ROOM_CODE_LEN):
            conn.send_envelope("ERROR", {"msg": "invalid room code"})
            return
        name = _sanitize_name(payload.get("name")) or "Player"
        room = self.rooms.get(code)
        if room is None:
            conn.send_envelope("ERROR", {"msg": f"room {code!r} not found"})
            return
        # Reconnect path: a disconnected slot with the same name still in the
        # engine. Reclaim it (any state — lobby or in-match) before rejecting
        # for "started" or "full".
        existing = next(
            (p for p in room.engine.state.players if p.name == name and not p.connected),
            None,
        )
        if existing is not None:
            room.connections[existing.player_id] = conn
            conn.player_id = existing.player_id
            conn.room_code = code
            conn.name = name
            room.engine.mark_reconnected(existing.player_id)
            conn.send_envelope("JOINED", {
                "room_code": code,
                "player_id": existing.player_id,
                "is_host": existing.is_host,
                "reconnected": True,
            })
            room.broadcast_event("RECONNECT", player_name=name)
            room.broadcast_state()
            print(f"[server] {name} reconnected to {code}")
            return
        # Fresh join: only allowed pre-match and with a free slot.
        if room.started:
            conn.send_envelope("ERROR", {"msg": "match already started"})
            return
        if room.n_players >= 4:
            conn.send_envelope("ERROR", {"msg": "room is full"})
            return
        # Reject duplicate names while connected — keeps reconnect identity unambiguous.
        if any(p.name == name for p in room.engine.state.players):
            conn.send_envelope("ERROR", {"msg": f"name {name!r} already taken in this room"})
            return
        player_id = uuid4().hex[:8]
        if not room.engine.join_room(player_id, name):
            conn.send_envelope("ERROR", {"msg": "join failed"})
            return
        room.connections[player_id] = conn
        conn.player_id = player_id
        conn.room_code = code
        conn.name = name
        conn.send_envelope("JOINED", {
            "room_code": code,
            "player_id": player_id,
            "is_host": False,
        })
        room.broadcast_event("JOIN", player_name=name)
        room.broadcast_state()
        print(f"[server] {name} joined {code}")

    def _on_leave_room(self, conn: Connection, payload: dict[str, Any]) -> None:
        del payload
        if conn.player_id is None or conn.room_code is None:
            return
        room = self.rooms.get(conn.room_code)
        if room is None:
            return
        leaving_name = conn.name
        room.engine.handle_action(conn.player_id, LeaveRoom())
        room.connections.pop(conn.player_id, None)
        room.broadcast_event("LEAVE", player_name=leaving_name)
        room.broadcast_state()
        conn.player_id = None
        conn.room_code = None

    def _on_action(self, conn: Connection, payload: dict[str, Any]) -> None:
        if conn.player_id is None or conn.room_code is None:
            conn.send_envelope("ACTION_REJECTED", {"reason": "not in a room"})
            return
        room = self.rooms.get(conn.room_code)
        if room is None:
            conn.send_envelope("ACTION_REJECTED", {"reason": "room gone"})
            return
        try:
            action = action_from_json(payload)
        except (KeyError, ValueError) as exc:
            conn.send_envelope("ACTION_REJECTED", {"reason": f"bad action: {exc}"})
            return
        # Handle AddBot on server directly (creates a bot player without a socket)
        if isinstance(action, AddBot):
            requester = next((p for p in room.engine.state.players if p.player_id == conn.player_id), None)
            if requester is None or not requester.is_host:
                conn.send_envelope("ACTION_REJECTED", {"reason": "Only host can add bots"})
                return
            if room.started:
                conn.send_envelope("ACTION_REJECTED", {"reason": "match already started"})
                return
            if room.n_players >= 4:
                conn.send_envelope("ACTION_REJECTED", {"reason": "room is full"})
                return
            # choose smallest available Bot N name
            existing = [p.name for p in room.engine.state.players if p.name.startswith("Bot ")]
            nums = set()
            for name in existing:
                try:
                    nums.add(int(name.split(" ")[1]))
                except Exception:
                    continue
            n = 1
            while n in nums:
                n += 1
            bot_name = f"Bot {n}"
            bot_id = uuid4().hex[:8]
            if not room.engine.join_room(bot_id, bot_name):
                conn.send_envelope("ACTION_REJECTED", {"reason": "join failed"})
                return
            room.bots[bot_id] = SimpleBot()
            room.clear_bot_timers_for(bot_id)
            room.broadcast_event("BOT_ADDED", bot_name=bot_name)
            room.broadcast_state()
            return
        before_players = {p.player_id: p.name for p in room.engine.state.players}
        before_host = next(
            (p.player_id for p in room.engine.state.players if p.is_host), None
        )
        before_reaction = room.engine.state.reaction_event.active
        before_started = room.engine.state.started
        before_ended = room.engine.state.ended
        ok, reason = room.engine.handle_action(conn.player_id, action)
        if not ok:
            conn.send_envelope("ACTION_REJECTED", {"reason": reason})
            return
        # Player removed by KickPlayer? Tear down their socket and emit KICK event.
        after_player_ids = {p.player_id for p in room.engine.state.players}
        for pid in set(before_players.keys()) - after_player_ids:
            kicked_conn = room.connections.pop(pid, None)
            room.broadcast_event(
                "KICK", player_name=before_players[pid], by_name=conn.name,
            )
            if kicked_conn is not None:
                kicked_conn.send_envelope("KICKED", {"reason": "kicked by host"})
                kicked_conn.close()
        after_host = next(
            (p.player_id for p in room.engine.state.players if p.is_host), None
        )
        if after_host and after_host != before_host:
            new_host = next(p for p in room.engine.state.players if p.is_host)
            room.broadcast_event("HOST_MIGRATED", new_host_name=new_host.name)
        if room.engine.state.reaction_event.active and not before_reaction:
            room.broadcast_event("REACTION_START")
        if room.engine.state.started and not before_started:
            room.broadcast_event("MATCH_START")
        if room.engine.state.ended and not before_ended:
            winner_id = room.engine.state.winner_id
            winner_name = next(
                (p.name for p in room.engine.state.players if p.player_id == winner_id),
                "?",
            )
            room.broadcast_event("MATCH_END", winner_name=winner_name)
        room.broadcast_state()

    def _on_chat(self, conn: Connection, payload: dict[str, Any]) -> None:
        if conn.player_id is None or conn.room_code is None:
            conn.send_envelope("ERROR", {"msg": "not in a room"})
            return
        room = self.rooms.get(conn.room_code)
        if room is None:
            conn.send_envelope("ERROR", {"msg": "room gone"})
            return
        if not conn.allow_chat():
            conn.send_envelope("ERROR", {"msg": "slow down — chat rate limited"})
            return
        msg = _sanitize_chat(payload.get("message"))
        if not msg:
            return
        room.broadcast_event("CHAT", player_name=conn.name or "Player", message=msg)

    # ------------------------------------------------------------------
    # disconnect
    # ------------------------------------------------------------------
    def _handle_disconnect(self, conn: Connection) -> None:
        with self.lock:
            conn.closed = True
            self.all_conns.discard(conn)
            try:
                conn.sock.close()
            except OSError:
                pass
            if conn.player_id is None or conn.room_code is None:
                return
            room = self.rooms.get(conn.room_code)
            if room is None:
                return
            # Drop the conn from the room's mapping but keep the player slot —
            # the engine's disconnect FSM owns timeouts.
            if room.connections.get(conn.player_id) is conn:
                room.connections.pop(conn.player_id, None)
            if not room.started:
                # Pre-match: instant leave (spec §7.2).
                room.engine.handle_action(conn.player_id, LeaveRoom())
                room.broadcast_event("LEAVE", player_name=conn.name)
            else:
                room.engine.mark_disconnected(conn.player_id)
                room.broadcast_event("DISCONNECT", player_name=conn.name)
            room.broadcast_state()


