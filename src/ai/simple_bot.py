from __future__ import annotations

import random
import time
from collections import Counter

from src.core.actions import (
    ChooseColor,
    ChooseDirection,
    ChooseTarget,
    DrawCard,
    PlayCard,
    Reaction,
)
from src.core.cards import Card, CardType, Color, NON_WINNING_FINAL_TYPES
from src.core.game_state import GameStateView


class SimpleBot:
    def _think(self, min_seconds: float = 5.0, max_seconds: float = 10.0) -> None:
        time.sleep(random.uniform(min_seconds, max_seconds))

    def choose_action(self, view: GameStateView, my_id: str, delay: bool = True) -> object:
        del my_id
        if delay:
            self._think()
        if not view.self_hand:
            return DrawCard()

        playable_indices = self._get_playable_indices(view)

        if view.pending_penalty > 0:
            stacking_idx = self._find_stacking_card(view, playable_indices)
            if stacking_idx is not None:
                return PlayCard(hand_index=stacking_idx)

        if len(view.self_hand) == 1 and playable_indices:
            idx = playable_indices[0]
            card = view.self_hand[idx]
            if card.card_type in NON_WINNING_FINAL_TYPES:
                return DrawCard()

        if playable_indices:
            number_idx = self._find_best_number_card(view, playable_indices)
            if number_idx is not None:
                return PlayCard(hand_index=number_idx)
            idx = playable_indices[0]
            return PlayCard(hand_index=idx)

        return DrawCard()

    def _get_playable_indices(self, view: GameStateView) -> list[int]:
        return [idx for idx, card in enumerate(view.self_hand) if self._is_legal_play(view, card)]

    def _is_legal_play(self, view: GameStateView, card: Card) -> bool:
        if view.pending_penalty > 0:
            if view.pending_penalty_min == 4:
                return card.card_type == CardType.WILD_DRAW_FOUR
            return card.card_type in (CardType.DRAW_TWO, CardType.WILD_DRAW_FOUR)

        top_card = view.top_card
        if top_card is None:
            return True
        if card.card_type == CardType.WILD or card.card_type == CardType.WILD_DRAW_FOUR:
            return True

        current_color = view.current_color or top_card.color
        if top_card.color == Color.WILD:
            return card.color == current_color or card.card_type in (
                CardType.WILD,
                CardType.WILD_DRAW_FOUR,
            )

        if card.color == current_color:
            return True

        if card.card_type == top_card.card_type:
            return True

        if (
            card.card_type == CardType.NUMBER
            and top_card.card_type == CardType.NUMBER
            and card.value == top_card.value
        ):
            return True

        return False

    def _find_stacking_card(self, view: GameStateView, playable_indices: list[int]) -> int | None:
        stack_candidates = []

        for idx in playable_indices:
            card = view.self_hand[idx]

            if card.card_type == CardType.WILD_DRAW_FOUR:
                stack_candidates.append((idx, 4))

            # +2 can only legally stack when pending is exactly 2, meaning the last
            # penalty card was definitively a +2. Any higher total is ambiguous since
            # it may have ended with a +4, which would make stacking a +2 illegal.
            elif card.card_type == CardType.DRAW_TWO and view.pending_penalty == 2:
                stack_candidates.append((idx, 2))

        if stack_candidates:
            stack_candidates.sort(key=lambda x: x[1], reverse=True)
            return stack_candidates[0][0]

        return None

    def _find_best_number_card(self, view: GameStateView, playable_indices: list[int]) -> int | None:
        number_indices = [
            idx for idx in playable_indices
            if view.self_hand[idx].card_type == CardType.NUMBER
        ]

        if not number_indices:
            return None

        if view.top_card and view.top_card.card_type == CardType.NUMBER:
            for idx in number_indices:
                if view.self_hand[idx].value == view.top_card.value:
                    return idx

        return number_indices[0]

    def choose_color(self, view: GameStateView, my_id: str, delay: bool = True) -> ChooseColor:
        del my_id
        if delay:
            self._think()
        color_counts = Counter()

        for card in view.self_hand:
            if card.color != Color.WILD:
                color_counts[card.color] += 1

        if color_counts:
            best_color = color_counts.most_common(1)[0][0]
            return ChooseColor(color=best_color)

        colors = [Color.RED, Color.GREEN, Color.BLUE, Color.YELLOW]
        return ChooseColor(color=random.choice(colors))

    def choose_direction(self, view: GameStateView, my_id: str, delay: bool = True) -> ChooseDirection:
        if delay:
            self._think()
        if not view.players:
            return ChooseDirection(direction=1)
        other_players = [p for p in view.players if p.player_id != my_id]

        if not other_players:
            return ChooseDirection(direction=1)

        max_cards_player = max(other_players, key=lambda p: p.card_count)

        my_pos = next((i for i, p in enumerate(view.players) if p.player_id == my_id), -1)
        max_pos = next((i for i, p in enumerate(view.players) if p.player_id == max_cards_player.player_id), -1)

        if my_pos == -1 or max_pos == -1:
            return ChooseDirection(direction=1)

        num_players = len(view.players)
        dist_forward = (max_pos - my_pos) % num_players
        dist_backward = (my_pos - max_pos) % num_players

        if dist_forward <= dist_backward:
            return ChooseDirection(direction=1)

        return ChooseDirection(direction=-1)

    def choose_target(self, view: GameStateView, my_id: str, delay: bool = True) -> ChooseTarget:
        if delay:
            self._think()
        other_players = [p for p in view.players if p.player_id != my_id]

        if not other_players:
            return ChooseTarget(target_player_id=view.players[0].player_id)

        min_cards_player = min(other_players, key=lambda p: p.card_count)
        return ChooseTarget(target_player_id=min_cards_player.player_id)

    def reaction(self, view: GameStateView, my_id: str, delay: bool = True) -> Reaction:
        del view, my_id
        if delay:
            time.sleep(random.uniform(0.8, 2.2))
        return Reaction()