from __future__ import annotations

from ..actions import PlayCard
from ..cards import CardType
from ..game_state import GameState
from .base import ValidationResult


class StackingRule:
    def applies_to_play(self, state: GameState, player_id: str, action: PlayCard) -> bool:
        return state.pending_penalty > 0

    def validate_play(self, state: GameState, player_id: str, action: PlayCard) -> ValidationResult:
        hand = state.hands[player_id]
        if action.hand_index < 0 or action.hand_index >= len(hand):
            return ValidationResult(False, "Invalid card index")
        card = hand[action.hand_index]
        if state.pending_penalty_min == 4:
            if card.card_type != CardType.WILD_DRAW_FOUR:
                return ValidationResult(False, "Must stack +4 on +4 chain")
            return ValidationResult(True)
        if card.card_type not in (CardType.DRAW_TWO, CardType.WILD_DRAW_FOUR):
            return ValidationResult(False, "Must stack +2 or +4 during penalty chain")
        return ValidationResult(True)
