from __future__ import annotations

import time
from dataclasses import dataclass, field

from .cards import Card, Color
from .deck import Deck
from .player import Player


@dataclass
class ReactionEvent:
    active: bool = False
    started_at: float = 0.0
    duration_sec: float = 3.0
    responses: dict[str, float] = field(default_factory=dict)

    def begin(self, duration_sec: float = 3.0) -> None:
        self.active = True
        self.started_at = time.monotonic()
        self.duration_sec = duration_sec
        self.responses.clear()

    def submit(self, player_id: str) -> bool:
        if not self.active or player_id in self.responses:
            return False
        self.responses[player_id] = time.monotonic()
        return True

    def time_left(self) -> float:
        if not self.active:
            return 0.0
        elapsed = time.monotonic() - self.started_at
        return max(0.0, self.duration_sec - elapsed)

    def deadline_passed(self) -> bool:
        return self.active and self.time_left() <= 0.0


@dataclass
class GameState:
    players: list[Player] = field(default_factory=list)
    hands: dict[str, list[Card]] = field(default_factory=dict)
    draw_pile: Deck = field(default_factory=Deck)
    discard_pile: list[Card] = field(default_factory=list)
    started: bool = False
    ended: bool = False
    winner_id: str | None = None
    turn_index: int = 0
    direction: int = 1
    pending_penalty: int = 0
    pending_penalty_min: int = 0
    current_color: Color | None = None
    top_card: Card | None = None
    awaiting_color_for_player: str | None = None
    awaiting_direction_for_player: str | None = None
    awaiting_target_for_player: str | None = None
    awaiting_played_card: Card | None = None
    may_play_drawn_for_player: str | None = None
    reaction_event: ReactionEvent = field(default_factory=ReactionEvent)
    room_code: str = "ABCD"

    def player_ids(self) -> list[str]:
        return [p.player_id for p in self.players]

    def current_player_id(self) -> str | None:
        if not self.players:
            return None
        return self.players[self.turn_index].player_id

    def next_turn(self, skip_count: int = 0) -> None:
        if not self.players:
            return
        step = 1 + skip_count
        self.turn_index = (self.turn_index + (self.direction * step)) % len(self.players)


@dataclass(frozen=True)
class PublicPlayerView:
    player_id: str
    name: str
    is_host: bool
    card_count: int


@dataclass(frozen=True)
class GameStateView:
    self_player_id: str
    players: list[PublicPlayerView]
    self_hand: list[Card]
    top_card: Card | None
    current_color: Color | None
    turn_player_id: str | None
    direction: int
    pending_penalty: int
    pending_penalty_min: int
    started: bool
    ended: bool
    winner_id: str | None
    draw_count: int
    room_code: str
    awaiting_color_for_player: str | None
    awaiting_direction_for_player: str | None
    awaiting_target_for_player: str | None
    may_play_drawn_for_player: str | None
    reaction_active: bool
    reaction_time_left: float
    reaction_responded_ids: list[str]
    log: list[str]


def to_view(state: GameState, self_player_id: str, log: list[str]) -> GameStateView:
    players = [
        PublicPlayerView(
            player_id=p.player_id,
            name=p.name,
            is_host=p.is_host,
            card_count=len(state.hands.get(p.player_id, [])),
        )
        for p in state.players
    ]
    return GameStateView(
        self_player_id=self_player_id,
        players=players,
        self_hand=list(state.hands.get(self_player_id, [])),
        top_card=state.top_card,
        current_color=state.current_color,
        turn_player_id=state.current_player_id(),
        direction=state.direction,
        pending_penalty=state.pending_penalty,
        pending_penalty_min=state.pending_penalty_min,
        started=state.started,
        ended=state.ended,
        winner_id=state.winner_id,
        draw_count=len(state.draw_pile),
        room_code=state.room_code,
        awaiting_color_for_player=state.awaiting_color_for_player,
        awaiting_direction_for_player=state.awaiting_direction_for_player,
        awaiting_target_for_player=state.awaiting_target_for_player,
        may_play_drawn_for_player=state.may_play_drawn_for_player,
        reaction_active=state.reaction_event.active,
        reaction_time_left=state.reaction_event.time_left(),
        reaction_responded_ids=list(state.reaction_event.responses.keys()),
        log=list(log[-8:]),
    )
