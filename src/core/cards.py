from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Color(str, Enum):
    RED = "red"
    GREEN = "green"
    BLUE = "blue"
    YELLOW = "yellow"
    WILD = "wild"


class CardType(str, Enum):
    NUMBER = "number"
    SKIP = "skip"
    REVERSE = "reverse"
    DRAW_TWO = "draw_two"
    WILD = "wild"
    WILD_DRAW_FOUR = "wild_draw_four"


ACTION_TYPES = {
    CardType.SKIP,
    CardType.REVERSE,
    CardType.DRAW_TWO,
    CardType.WILD,
    CardType.WILD_DRAW_FOUR,
}

NON_WINNING_FINAL_TYPES = ACTION_TYPES


@dataclass(frozen=True)
class Card:
    color: Color
    card_type: CardType
    value: int | None = None

    def code(self) -> str:
        if self.card_type == CardType.NUMBER:
            return f"{self.color.value}_{self.value}"
        return f"{self.color.value}_{self.card_type.value}"

