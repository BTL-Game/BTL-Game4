from __future__ import annotations

from typing import Protocol

from src.core.game_state import GameStateView


class BotStrategy(Protocol):
    def choose_action(self, view: GameStateView, my_id: str) -> object:
        ...
