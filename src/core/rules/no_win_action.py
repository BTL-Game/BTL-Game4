from __future__ import annotations

from ..actions import PlayCard
from ..cards import NON_WINNING_FINAL_TYPES
from ..game_state import GameState
from .base import ValidationResult


class NoWinActionRule:
    def applies_to_play(self, state: GameState, player_id: str, action: PlayCard) -> bool:
        return True

    def validate_play(self, state: GameState, player_id: str, action: PlayCard) -> ValidationResult:
        hand = state.hands[player_id]
        if action.hand_index < 0 or action.hand_index >= len(hand):
            return ValidationResult(False, "Invalid card index")
        card = hand[action.hand_index]
        if len(hand) == 1 and card.card_type in NON_WINNING_FINAL_TYPES:
            return ValidationResult(False, "Cannot win with an action/special card")
        return ValidationResult(True)
