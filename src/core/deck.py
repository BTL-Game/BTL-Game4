from __future__ import annotations

import random
from dataclasses import dataclass, field

from .cards import Card, CardType, Color


def build_standard_uno_deck() -> list[Card]:
    deck: list[Card] = []
    for color in [Color.RED, Color.GREEN, Color.BLUE, Color.YELLOW]:
        for value in range(10):
            copies = 1 if value == 0 else 2
            for _ in range(copies):
                deck.append(Card(color=color, card_type=CardType.NUMBER, value=value))
        for action_type in [CardType.SKIP, CardType.REVERSE, CardType.DRAW_TWO]:
            for _ in range(2):
                deck.append(Card(color=color, card_type=action_type))
    for _ in range(4):
        deck.append(Card(color=Color.WILD, card_type=CardType.WILD))
        deck.append(Card(color=Color.WILD, card_type=CardType.WILD_DRAW_FOUR))
    return deck


@dataclass
class Deck:
    cards: list[Card] = field(default_factory=build_standard_uno_deck)

    def shuffle(self) -> None:
        random.shuffle(self.cards)

    def draw(self) -> Card | None:
        if not self.cards:
            return None
        return self.cards.pop()

    def extend(self, cards: list[Card]) -> None:
        self.cards.extend(cards)

    def __len__(self) -> int:
        return len(self.cards)
