from __future__ import annotations

from ..actions import PlayCard
from ..game_state import GameState
from .base import ValidationResult
from .asian import AsianPlayRule
from .no_win_action import NoWinActionRule
from .stacking import StackingRule
from .standard import StandardPlayRule
from ..modes import MODE_ASIAN


class RuleRegistry:
    def __init__(self) -> None:
        self.no_win_action = NoWinActionRule()
        self.stacking = StackingRule()
        self.standard = StandardPlayRule()
        self.asian = AsianPlayRule()

    def validate_play(self, state: GameState, player_id: str, action: PlayCard) -> ValidationResult:
        if state.mode == MODE_ASIAN:
            return self.asian.validate_play(state, player_id, action)
        checks = [self.no_win_action]
        if state.pending_penalty > 0:
            checks.append(self.stacking)
        else:
            checks.append(self.standard)
        for rule in checks:
            result = rule.validate_play(state, player_id, action)
            if not result.ok:
                return result
        return ValidationResult(True)
