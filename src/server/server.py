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

from src.core.actions import LeaveRoom
from src.core.engine import GameEngine
from src.core.game_state import to_view
from src.network.codec import action_from_json, view_to_json


ROOM_GC_AFTER_SEC = 10.0
TICK_HZ = 4.0  # 4 ticks per second; tight enough for 30s/60s timers + reaction.
HEARTBEAT_TIMEOUT_SEC = 15.0  # close conn after no PING/data for this long.


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
            after_player_ids = {p.player_id for p in room.engine.state.players}
            removed = set(before_players.keys()) - after_player_ids
            for pid in removed:
                conn = room.connections.pop(pid, None)
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
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    try:
                        env = json.loads(line.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        conn.send_envelope("ERROR", {"msg": "malformed JSON"})
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
        handler = {
            "LIST_ROOMS": self._on_list_rooms,
            "CREATE_ROOM": self._on_create_room,
            "JOIN_ROOM": self._on_join_room,
            "LEAVE_ROOM": self._on_leave_room,
            "ACTION": self._on_action,
            "PING": self._on_ping,
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
        conn.send_envelope("PONG", {"t": payload.get("t", 0.0)})

    def _on_list_rooms(self, conn: Connection, payload: dict[str, Any]) -> None:
        rooms = [r.to_summary() for r in self.rooms.values() if r.visible]
        conn.send_envelope("ROOM_LIST", {"rooms": rooms})

    def _gen_room_code(self) -> str:
        while True:
            code = "".join(random.choice(string.ascii_uppercase) for _ in range(4))
            if code not in self.rooms:
                return code

    def _on_create_room(self, conn: Connection, payload: dict[str, Any]) -> None:
        if conn.player_id is not None:
            conn.send_envelope("ERROR", {"msg": "already in a room"})
            return
        name = (payload.get("name") or "").strip() or "Player"
        host_id = uuid4().hex[:8]
        engine = GameEngine()
        engine.create_room(host_id, name)
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
        code = (payload.get("code") or "").strip().upper()
        name = (payload.get("name") or "").strip() or "Player"
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


