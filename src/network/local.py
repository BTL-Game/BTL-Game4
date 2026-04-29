from __future__ import annotations

from typing import Callable
from uuid import uuid4

from src.core.engine import GameEngine
from src.core.game_state import GameStateView, to_view


class LocalNetwork:
    def __init__(self) -> None:
        self.engine = GameEngine()
        self._state_callbacks: list[Callable[[str, GameStateView], None]] = []

    def host_room(self, player_name: str) -> str:
        player_id = uuid4().hex[:8]
        self.engine.create_room(player_id, player_name)
        self._broadcast_all()
        return player_id

    def join_room(self, room_code: str, player_name: str) -> str:
        del room_code
        player_id = uuid4().hex[:8]
        if not self.engine.join_room(player_id, player_name):
            return ""
        self._broadcast_all()
        return player_id

    def send(self, player_id: str, action: object) -> tuple[bool, str]:
        ok, reason = self.engine.handle_action(player_id, action)
        self._broadcast_all()
        return ok, reason

    def on_state(self, callback: Callable[[str, GameStateView], None]) -> None:
        self._state_callbacks.append(callback)

    def _broadcast_all(self) -> None:
        for p in self.engine.state.players:
            view = to_view(self.engine.state, p.player_id, self.engine.log)
            for cb in self._state_callbacks:
                cb(p.player_id, view)

    def update(self) -> None:
        self.engine.tick()
        self._broadcast_all()
