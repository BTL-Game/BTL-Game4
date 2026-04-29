from __future__ import annotations

from ..actions import PlayCard
from ..cards import CardType
from ..game_state import GameState
from .base import ValidationResult


class RuleEight:
    def applies_to_play(self, state: GameState, player_id: str, action: PlayCard) -> bool:
        hand = state.hands[player_id]
        if action.hand_index < 0 or action.hand_index >= len(hand):
            return False
        card = hand[action.hand_index]
        return card.card_type == CardType.NUMBER and card.value == 8

    def validate_play(self, state: GameState, player_id: str, action: PlayCard) -> ValidationResult:
        return ValidationResult(True)
