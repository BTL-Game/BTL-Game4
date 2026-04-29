from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..actions import PlayCard
from ..game_state import GameState


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    reason: str = ""


class RuleHandler(Protocol):
    def applies_to_play(self, state: GameState, player_id: str, action: PlayCard) -> bool:
        ...

    def validate_play(self, state: GameState, player_id: str, action: PlayCard) -> ValidationResult:
        ...
