"""Client-side TCP wrapper that satisfies NetworkInterface.

Threading model:
- Reader thread: pulls newline-delimited JSON envelopes off the socket and
  appends them to an in-memory queue.
- Pygame thread (calls .update() each frame): drains the queue, dispatches
  STATE envelopes to the registered callback.

This keeps pygame's render loop strictly non-blocking. send() writes from the
pygame thread; small payloads + TCP NODELAY make this fine in practice.
"""
from __future__ import annotations

import json
import socket
import threading
import time
from collections import deque
from typing import Any, Callable


PING_INTERVAL_SEC = 5.0

from src.core.game_state import GameStateView
from src.network.codec import action_to_json, view_from_json


class SocketClientNetwork:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.sock: socket.socket | None = None
        self._buf = b""
        self._inbox: deque[dict[str, Any]] = deque()
        self._lock = threading.Lock()
        self._reader: threading.Thread | None = None
        self._closed = False
        self._last_ping_at: float = 0.0
        self._event_queue: deque[dict[str, Any]] = deque()

        # Set by JOINED envelope.
        self.player_id: str = ""
        self.room_code: str = ""
        self.is_host: bool = False

        # Cached lobby browser data; refreshed when ROOM_LIST arrives.
        self.room_list: list[dict[str, Any]] = []
        self.last_error: str = ""

        self._state_callbacks: list[Callable[[str, GameStateView], None]] = []

    # ------------------------------------------------------------------
    # connection lifecycle
    # ------------------------------------------------------------------
    def connect(self) -> None:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        s.connect((self.host, self.port))
        self.sock = s
        self._reader = threading.Thread(target=self._read_loop, name="net-reader", daemon=True)
        self._reader.start()

    def close(self) -> None:
        self._closed = True
        if self.sock is not None:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    # ------------------------------------------------------------------
    # outbound helpers
    # ------------------------------------------------------------------
    def _send(self, msg_type: str, payload: dict[str, Any] | None = None) -> bool:
        if self.sock is None or self._closed:
            return False
        env = {"type": msg_type, "payload": payload or {}}
        try:
            self.sock.sendall((json.dumps(env) + "\n").encode("utf-8"))
            return True
        except OSError:
            self._closed = True
            return False

    def list_rooms(self) -> None:
        self._send("LIST_ROOMS")

    # ------------------------------------------------------------------
    # NetworkInterface
    # ------------------------------------------------------------------
    def host_room(self, player_name: str) -> str:
        self._send("CREATE_ROOM", {"name": player_name})
        return ""  # actual id arrives async via JOINED

    def join_room(self, room_code: str, player_name: str) -> str:
        self._send("JOIN_ROOM", {"code": room_code, "name": player_name})
        return ""

    def send(self, player_id: str, action: object) -> tuple[bool, str]:
        del player_id  # server identifies us by socket
        self._send("ACTION", action_to_json(action))
        # Server reports rejections via ACTION_REJECTED; surface via last_error.
        err = self.last_error
        self.last_error = ""
        return (err == ""), err

    def on_state(self, callback: Callable[[str, GameStateView], None]) -> None:
        self._state_callbacks.append(callback)

    def update(self) -> None:
        # Drain inbox under lock, then dispatch outside lock.
        with self._lock:
            envs = list(self._inbox)
            self._inbox.clear()
        for env in envs:
            self._handle(env)
        # Heartbeat: keep the server's idle timer fresh.
        now = time.monotonic()
        if now - self._last_ping_at >= PING_INTERVAL_SEC:
            self._last_ping_at = now
            self._send("PING", {"t": now})

    def pop_event(self) -> dict[str, Any] | None:
        if not self._event_queue:
            return None
        return self._event_queue.popleft()

    # ------------------------------------------------------------------
    # reader thread
    # ------------------------------------------------------------------
    def _read_loop(self) -> None:
        assert self.sock is not None
        sock = self.sock
        while not self._closed:
            try:
                chunk = sock.recv(8192)
            except OSError:
                break
            if not chunk:
                break
            self._buf += chunk
            while b"\n" in self._buf:
                line, self._buf = self._buf.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    env = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                with self._lock:
                    self._inbox.append(env)
        self._closed = True

    # ------------------------------------------------------------------
    # inbound dispatch (pygame thread)
    # ------------------------------------------------------------------
    def _handle(self, env: dict[str, Any]) -> None:
        msg_type = env.get("type")
        payload = env.get("payload") or {}
        if msg_type == "STATE":
            view = view_from_json(payload)
            for cb in self._state_callbacks:
                cb(self.player_id, view)
        elif msg_type == "JOINED":
            self.player_id = payload.get("player_id", "")
            self.room_code = payload.get("room_code", "")
            self.is_host = bool(payload.get("is_host"))
        elif msg_type == "ROOM_LIST":
            self.room_list = list(payload.get("rooms", []))
        elif msg_type == "ACTION_REJECTED":
            self.last_error = str(payload.get("reason", "rejected"))
        elif msg_type == "ERROR":
            self.last_error = str(payload.get("msg", "error"))
        elif msg_type == "KICKED":
            self.last_error = str(payload.get("reason", "kicked"))
            # Mark our session as out of the room; UI will route us back to menu.
            self.player_id = ""
            self.room_code = ""
            self.is_host = False
        elif msg_type == "EVENT":
            self._event_queue.append(payload)
        elif msg_type == "PONG":
            pass
