from __future__ import annotations

from dataclasses import dataclass

from .cards import Color


@dataclass(frozen=True)
class StartMatch:
    pass


@dataclass(frozen=True)
class LeaveRoom:
    pass


@dataclass(frozen=True)
class DrawCard:
    pass


@dataclass(frozen=True)
class PlayCard:
    hand_index: int


@dataclass(frozen=True)
class ChooseColor:
    color: Color


@dataclass(frozen=True)
class ChooseDirection:
    direction: int


@dataclass(frozen=True)
class ChooseTarget:
    target_player_id: str


@dataclass(frozen=True)
class Reaction:
    pass
