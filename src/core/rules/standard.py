from __future__ import annotations

from ..actions import PlayCard
from ..cards import CardType, Color
from ..game_state import GameState
from .base import ValidationResult


class StandardPlayRule:
    def applies_to_play(self, state: GameState, player_id: str, action: PlayCard) -> bool:
        return True

    def validate_play(self, state: GameState, player_id: str, action: PlayCard) -> ValidationResult:
        hand = state.hands[player_id]
        if action.hand_index < 0 or action.hand_index >= len(hand):
            return ValidationResult(False, "Invalid card index")
        card = hand[action.hand_index]
        if state.top_card is None:
            return ValidationResult(True)
        if card.card_type in (CardType.WILD, CardType.WILD_DRAW_FOUR):
            return ValidationResult(True)
        current_color = state.current_color or state.top_card.color
        if card.color == current_color:
            return ValidationResult(True)
        top = state.top_card
        if card.card_type == CardType.NUMBER and top.card_type == CardType.NUMBER and card.value == top.value:
            return ValidationResult(True)
        if card.card_type == top.card_type and card.card_type != CardType.NUMBER:
            return ValidationResult(True)
        return ValidationResult(False, "Card is not legally playable")
