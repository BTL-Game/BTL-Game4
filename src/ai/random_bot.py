from __future__ import annotations

import random

from src.core.actions import DrawCard, PlayCard
from src.core.game_state import GameStateView


class RandomBot:
    def choose_action(self, view: GameStateView, my_id: str) -> object:
        del my_id
        if view.self_hand and random.random() < 0.7:
            return PlayCard(hand_index=random.randrange(len(view.self_hand)))
        return DrawCard()
