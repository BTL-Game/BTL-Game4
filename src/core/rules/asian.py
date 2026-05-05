from __future__ import annotations

from ..actions import PlayCard
from ..cards import ACTION_TYPES, CardType
from ..game_state import GameState
from .base import ValidationResult


class AsianPlayRule:
    def validate_play(self, state: GameState, player_id: str, action: PlayCard) -> ValidationResult:
        hand = state.hands[player_id]
        if action.hand_index < 0 or action.hand_index >= len(hand):
            return ValidationResult(False, "Invalid card index")
        if state.turn_play_count >= state.turn_play_limit:
            return ValidationResult(False, "Turn play limit reached")
        card = hand[action.hand_index]
        if card.card_type in (CardType.WILD, CardType.WILD_DRAW_FOUR):
            return ValidationResult(False, "Wild cards are not allowed in Asian mode")
        if card.card_type in ACTION_TYPES and state.turn_action_card is not None:
            return ValidationResult(False, "Only one action card per turn")
        # Color of the turn overrides normal color matching.
        if state.turn_color is not None and card.color == state.turn_color:
            return ValidationResult(True)
        top = state.top_card
        if top is None:
            return ValidationResult(True)
        if card.card_type == CardType.NUMBER and top.card_type == CardType.NUMBER and card.value == top.value:
            return ValidationResult(True)
        if card.card_type == top.card_type and card.card_type != CardType.NUMBER:
            return ValidationResult(True)
        return ValidationResult(False, "Card is not legally playable")
