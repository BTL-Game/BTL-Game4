from __future__ import annotations

from typing import Callable, Protocol

from src.core.game_state import GameStateView


class NetworkInterface(Protocol):
    def host_room(self, player_name: str, mode: str = "basic") -> str:
        ...

    def join_room(self, room_code: str, player_name: str) -> str:
        ...

    def send(self, player_id: str, action: object) -> tuple[bool, str]:
        ...

    def send_chat(self, message: str) -> None:
        ...

    def on_state(self, callback: Callable[[str, GameStateView], None]) -> None:
        ...

    def update(self) -> None:
        ...
