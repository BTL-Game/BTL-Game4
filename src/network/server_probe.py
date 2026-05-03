"""Background prober for advertised servers.

Each entry in the configured server list is polled in its own daemon thread:
open a TCP connection, send {type: SERVER_STATUS}, read a single line of
response with a tight timeout, close. Results are cached as a snapshot dict
keyed by server id and read by the UI thread.

The probe is read-only — no auth, no game state — so it's safe to run
without a player identity.
"""
from __future__ import annotations

import json
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ServerEntry:
    id: str
    label: str
    host: str
    port: int


@dataclass
class ServerStatus:
    online: bool = False
    latency_ms: Optional[int] = None
    n_players: int = 0
    n_visible_rooms: int = 0
    n_connections: int = 0
    max_connections: int = 0
    last_checked: float = 0.0
    error: str = ""


PROBE_INTERVAL_SEC = 5.0
PROBE_TIMEOUT_SEC = 2.5


class ServerProbe:
    def __init__(self, servers: list[ServerEntry]) -> None:
        self.servers = list(servers)
        self._status: dict[str, ServerStatus] = {s.id: ServerStatus() for s in servers}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        for s in self.servers:
            t = threading.Thread(
                target=self._probe_loop, args=(s,), name=f"probe-{s.id}", daemon=True
            )
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()

    def snapshot(self) -> dict[str, ServerStatus]:
        with self._lock:
            return {sid: ServerStatus(**vars(st)) for sid, st in self._status.items()}

    def _probe_loop(self, entry: ServerEntry) -> None:
        # Stagger initial probes slightly so they don't all fire on the same tick.
        time.sleep(0.05)
        while not self._stop.is_set():
            self._probe_once(entry)
            # Wait but wake up promptly on stop().
            self._stop.wait(PROBE_INTERVAL_SEC)

    def _probe_once(self, entry: ServerEntry) -> None:
        result = ServerStatus(last_checked=time.time())
        t0 = time.monotonic()
        sock: Optional[socket.socket] = None
        try:
            sock = socket.create_connection((entry.host, entry.port), timeout=PROBE_TIMEOUT_SEC)
            sock.settimeout(PROBE_TIMEOUT_SEC)
            req = (json.dumps({"type": "SERVER_STATUS", "payload": {}}) + "\n").encode("utf-8")
            sock.sendall(req)
            buf = b""
            # Read one full line (server replies with a single SERVER_STATUS envelope).
            while b"\n" not in buf and len(buf) < 8192:
                chunk = sock.recv(2048)
                if not chunk:
                    break
                buf += chunk
            if b"\n" in buf:
                line = buf.split(b"\n", 1)[0]
            else:
                line = buf
            env = json.loads(line.decode("utf-8")) if line else {}
            payload = env.get("payload") or {}
            if env.get("type") == "SERVER_STATUS":
                result.online = True
                result.latency_ms = max(0, int((time.monotonic() - t0) * 1000))
                result.n_players = int(payload.get("n_players", 0))
                result.n_visible_rooms = int(payload.get("n_visible_rooms", 0))
                result.n_connections = int(payload.get("n_connections", 0))
                result.max_connections = int(payload.get("max_connections", 0))
            else:
                result.error = "unexpected response"
        except (socket.timeout, OSError, ValueError) as exc:
            result.error = str(exc) or "unreachable"
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
        with self._lock:
            self._status[entry.id] = result


# Default advertised servers. Order matters: the first is the default selection.
DEFAULT_SERVERS: list[ServerEntry] = [
    ServerEntry(id="sun", label="Sun", host="127.0.0.1", port=5555),
    ServerEntry(id="moon", label="Moon", host="143.244.158.201", port=5555),
]
