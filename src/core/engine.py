from __future__ import annotations

import random
import string
import time

from .actions import (
    ChooseColor,
    ChooseDirection,
    ChooseTarget,
    DrawCard,
    KickPlayer,
    LeaveRoom,
    PlayCard,
    Reaction,
    StartMatch,
)


TURN_SKIP_AFTER_SECONDS = 30.0
REMOVE_AFTER_TOTAL_SECONDS = 60.0
from .cards import Card, CardType, Color
from .events import EventBus
from .game_state import GameState
from .player import Player
from .rules.registry import RuleRegistry


class GameEngine:
    def __init__(self, event_bus: EventBus | None = None, rules: RuleRegistry | None = None) -> None:
        self.event_bus = event_bus or EventBus()
        self.rules = rules or RuleRegistry()
        self.state = GameState()
        self.log: list[str] = []

    def _push_log(self, message: str) -> None:
        self.log.append(message)
        self.event_bus.publish("log", message)

    def create_room(self, host_id: str, host_name: str) -> None:
        self.state = GameState()
        self.state.room_code = "".join(random.choice(string.digits) for _ in range(8))
        self.state.players = [
            Player(player_id=host_id, name=host_name, is_host=True, joined_at=time.monotonic())
        ]
        self.state.hands[host_id] = []

    def join_room(self, player_id: str, name: str) -> bool:
        if self.state.started or len(self.state.players) >= 4:
            return False
        self.state.players.append(
            Player(player_id=player_id, name=name, is_host=False, joined_at=time.monotonic())
        )
        self.state.hands[player_id] = []
        self._push_log(f"{name} joined room.")
        return True

    def _find_player(self, player_id: str) -> Player | None:
        for p in self.state.players:
            if p.player_id == player_id:
                return p
        return None

    def mark_disconnected(self, player_id: str) -> None:
        p = self._find_player(player_id)
        if p is None or not p.connected:
            return
        p.connected = False
        p.disconnected_at = time.monotonic()
        self._push_log(f"{p.name} disconnected.")

    def mark_reconnected(self, player_id: str) -> None:
        p = self._find_player(player_id)
        if p is None or p.connected:
            return
        if p.disconnected_at is not None:
            p.total_disconnect_seconds += time.monotonic() - p.disconnected_at
        p.connected = True
        p.disconnected_at = None
        self._push_log(f"{p.name} reconnected.")

    def _current_disconnect_duration(self, p: Player) -> float:
        if p.connected or p.disconnected_at is None:
            return 0.0
        return time.monotonic() - p.disconnected_at

    def _cumulative_disconnect(self, p: Player) -> float:
        return p.total_disconnect_seconds + self._current_disconnect_duration(p)

    def _remove_player(self, player_id: str, reason: str) -> None:
        p = self._find_player(player_id)
        if p is None:
            return
        was_host = p.is_host
        was_current_turn = self.state.current_player_id() == player_id
        idx = self.state.players.index(p)
        self.state.players.pop(idx)
        self.state.hands.pop(player_id, None)
        if self.state.awaiting_color_for_player == player_id:
            self.state.awaiting_color_for_player = None
            self.state.awaiting_played_card = None
        if self.state.awaiting_direction_for_player == player_id:
            self.state.awaiting_direction_for_player = None
            self.state.awaiting_played_card = None
        if self.state.awaiting_target_for_player == player_id:
            self.state.awaiting_target_for_player = None
            self.state.awaiting_played_card = None
        if self.state.may_play_drawn_for_player == player_id:
            self.state.may_play_drawn_for_player = None
        if self.state.players:
            if idx <= self.state.turn_index and self.state.turn_index > 0:
                self.state.turn_index -= 1
            self.state.turn_index %= len(self.state.players)
        else:
            self.state.turn_index = 0
        self._push_log(f"{p.name} removed ({reason}).")
        if self.state.started and not self.state.ended:
            if len(self.state.players) == 1:
                self.state.ended = True
                self.state.winner_id = self.state.players[0].player_id
                self._push_log(f"{self.state.players[0].name} wins by walkover!")
                return
            if len(self.state.players) == 0:
                self.state.ended = True
                return
            if was_current_turn:
                # turn_index now points at next player automatically after pop
                pass
        if was_host:
            self._promote_new_host()

    def _promote_new_host(self) -> None:
        survivors = [p for p in self.state.players if p.connected]
        pool = survivors if survivors else list(self.state.players)
        if not pool:
            return
        new_host = min(pool, key=lambda p: p.joined_at)
        for p in self.state.players:
            p.is_host = (p.player_id == new_host.player_id)
        self._push_log(f"{new_host.name} is now the host.")

    def kick_player(self, requester_id: str, target_id: str) -> tuple[bool, str]:
        requester = self._find_player(requester_id)
        if requester is None or not requester.is_host:
            return False, "Only host can kick"
        if requester_id == target_id:
            return False, "Cannot kick yourself"
        if self._find_player(target_id) is None:
            return False, "Target not in room"
        self._remove_player(target_id, reason="kicked")
        return True, ""

    def _draw_card_or_rebuild(self) -> Card | None:
        card = self.state.draw_pile.draw()
        if card is not None:
            return card
        if len(self.state.discard_pile) <= 1:
            return None
        keep_top = self.state.discard_pile.pop()
        refill = self.state.discard_pile[:]
        self.state.discard_pile = [keep_top]
        self.state.draw_pile.extend(refill)
        self.state.draw_pile.shuffle()
        return self.state.draw_pile.draw()

    def start_match(self) -> bool:
        if self.state.started or len(self.state.players) < 2:
            return False
        self.state.started = True
        self.state.draw_pile.shuffle()
        for p in self.state.players:
            self.state.hands[p.player_id] = []
        for _ in range(7):
            for p in self.state.players:
                c = self._draw_card_or_rebuild()
                if c is not None:
                    self.state.hands[p.player_id].append(c)
        while True:
            c = self._draw_card_or_rebuild()
            if c is None:
                break
            self.state.discard_pile.append(c)
            self.state.top_card = c
            if c.card_type not in (CardType.WILD, CardType.WILD_DRAW_FOUR):
                self.state.current_color = c.color
                break
        self._push_log("Match started.")
        return True

    def _player_name(self, player_id: str) -> str:
        for p in self.state.players:
            if p.player_id == player_id:
                return p.name
        return player_id

    def handle_action(self, player_id: str, action: object) -> tuple[bool, str]:
        self.tick()
        if isinstance(action, StartMatch):
            if not self.state.players or self.state.players[0].player_id != player_id:
                return False, "Only host can start match"
            return (self.start_match(), "")
        if isinstance(action, LeaveRoom):
            return self._handle_leave(player_id)
        if isinstance(action, KickPlayer):
            return self.kick_player(player_id, action.target_player_id)
        if not self.state.started or self.state.ended:
            return False, "Match has not started or already ended"
        if isinstance(action, Reaction):
            return self._handle_reaction(player_id)
        if self.state.reaction_event.active:
            return False, "Only reaction input is allowed now"
        if self.state.current_player_id() != player_id:
            return False, "Not your turn"
        if isinstance(action, DrawCard):
            return self._handle_draw(player_id)
        if isinstance(action, PlayCard):
            return self._handle_play(player_id, action)
        if isinstance(action, ChooseColor):
            return self._handle_choose_color(player_id, action)
        if isinstance(action, ChooseDirection):
            return self._handle_choose_direction(player_id, action)
        if isinstance(action, ChooseTarget):
            return self._handle_choose_target(player_id, action)
        return False, "Unknown action"

    def _handle_leave(self, player_id: str) -> tuple[bool, str]:
        if not self.state.started:
            self.state.players = [p for p in self.state.players if p.player_id != player_id]
            self.state.hands.pop(player_id, None)
            return True, ""
        self._remove_player(player_id, reason="left match")
        return True, ""

    def _handle_reaction(self, player_id: str) -> tuple[bool, str]:
        if not self.state.reaction_event.active:
            return False, "No reaction event active"
        accepted = self.state.reaction_event.submit(player_id)
        if not accepted:
            return False, "Already reacted"
        self._push_log(f"{self._player_name(player_id)} reacted.")
        self._resolve_reaction_if_ready()
        return True, ""

    def _handle_draw(self, player_id: str) -> tuple[bool, str]:
        # If player already drew this turn (post-draw decision pending),
        # second DrawCard click means "pass" -> end turn.
        if self.state.may_play_drawn_for_player == player_id:
            self.state.may_play_drawn_for_player = None
            self.state.next_turn()
            return True, ""
        if self.state.pending_penalty > 0:
            for _ in range(self.state.pending_penalty):
                c = self._draw_card_or_rebuild()
                if c is not None:
                    self.state.hands[player_id].append(c)
            self._push_log(f"{self._player_name(player_id)} drew {self.state.pending_penalty} penalty cards.")
            self.state.pending_penalty = 0
            self.state.pending_penalty_min = 0
            self.state.next_turn()
            return True, ""
        c = self._draw_card_or_rebuild()
        if c is not None:
            self.state.hands[player_id].append(c)
        self._push_log(f"{self._player_name(player_id)} drew a card.")
        # Spec: if drawn card is legally playable, the player may play it now.
        if c is not None and self._is_card_playable(c):
            self.state.may_play_drawn_for_player = player_id
            return True, ""
        self.state.next_turn()
        return True, ""

    def _is_card_playable(self, card: Card) -> bool:
        from .cards import CardType as _CT
        if card.card_type in (_CT.WILD, _CT.WILD_DRAW_FOUR):
            return True
        if self.state.top_card is None:
            return True
        if card.color == self.state.current_color:
            return True
        top = self.state.top_card
        if card.card_type == _CT.NUMBER and top.card_type == _CT.NUMBER and card.value == top.value:
            return True
        if card.card_type == top.card_type and card.card_type != _CT.NUMBER:
            return True
        return False

    def _handle_play(self, player_id: str, action: PlayCard) -> tuple[bool, str]:
        result = self.rules.validate_play(self.state, player_id, action)
        if not result.ok:
            return False, result.reason
        self.state.may_play_drawn_for_player = None
        hand = self.state.hands[player_id]
        card = hand.pop(action.hand_index)
        self.state.discard_pile.append(card)
        self.state.top_card = card
        self.state.current_color = card.color if card.color != Color.WILD else self.state.current_color
        self._push_log(f"{self._player_name(player_id)} played {card.code()}.")
        if card.card_type == CardType.WILD:
            self.state.awaiting_color_for_player = player_id
            self.state.awaiting_played_card = card
            return True, ""
        if card.card_type == CardType.WILD_DRAW_FOUR:
            self.state.pending_penalty += 4
            self.state.pending_penalty_min = 4
            self.state.awaiting_color_for_player = player_id
            self.state.awaiting_played_card = card
            return True, ""
        if card.card_type == CardType.DRAW_TWO:
            self.state.pending_penalty += 2
            self.state.pending_penalty_min = 2
            self.state.next_turn()
            return self._check_win_then_continue(player_id)
        if card.card_type == CardType.SKIP:
            self.state.next_turn(skip_count=1)
            return self._check_win_then_continue(player_id)
        if card.card_type == CardType.REVERSE:
            self.state.direction *= -1
            self.state.next_turn(skip_count=1 if len(self.state.players) == 2 else 0)
            return self._check_win_then_continue(player_id)
        if card.card_type == CardType.NUMBER and card.value == 0:
            self.state.awaiting_direction_for_player = player_id
            self.state.awaiting_played_card = card
            return True, ""
        if card.card_type == CardType.NUMBER and card.value == 7:
            self.state.awaiting_target_for_player = player_id
            self.state.awaiting_played_card = card
            return True, ""
        if card.card_type == CardType.NUMBER and card.value == 8:
            self.state.reaction_event.begin(3.0)
            self._push_log("Reaction event started!")
            self.state.next_turn()
            return self._check_win_then_continue(player_id)
        self.state.next_turn()
        return self._check_win_then_continue(player_id)

    def _handle_choose_color(self, player_id: str, action: ChooseColor) -> tuple[bool, str]:
        if self.state.awaiting_color_for_player != player_id:
            return False, "Not awaiting color from you"
        if action.color == Color.WILD:
            return False, "Choose a non-wild color"
        self.state.current_color = action.color
        self.state.awaiting_color_for_player = None
        self.state.awaiting_played_card = None
        self.state.next_turn()
        return self._check_win_then_continue(player_id)

    def _handle_choose_direction(self, player_id: str, action: ChooseDirection) -> tuple[bool, str]:
        if self.state.awaiting_direction_for_player != player_id:
            return False, "Not awaiting direction from you"
        if action.direction not in (-1, 1):
            return False, "Direction must be -1 or 1"
        ids = self.state.player_ids()
        old_hands = {pid: list(self.state.hands[pid]) for pid in ids}
        for idx, pid in enumerate(ids):
            target_idx = (idx + action.direction) % len(ids)
            self.state.hands[ids[target_idx]] = old_hands[pid]
        self.state.awaiting_direction_for_player = None
        self.state.awaiting_played_card = None
        self._push_log("Rule 0 hand pass resolved.")
        self.state.next_turn()
        return self._check_win_then_continue(player_id)

    def _handle_choose_target(self, player_id: str, action: ChooseTarget) -> tuple[bool, str]:
        if self.state.awaiting_target_for_player != player_id:
            return False, "Not awaiting target from you"
        if action.target_player_id == player_id or action.target_player_id not in self.state.hands:
            return False, "Invalid target"
        self.state.hands[player_id], self.state.hands[action.target_player_id] = (
            self.state.hands[action.target_player_id],
            self.state.hands[player_id],
        )
        self.state.awaiting_target_for_player = None
        self.state.awaiting_played_card = None
        self._push_log(f"{self._player_name(player_id)} swapped hand with {self._player_name(action.target_player_id)}.")
        self.state.next_turn()
        return self._check_win_then_continue(player_id)

    def _check_win_then_continue(self, player_id: str) -> tuple[bool, str]:
        if len(self.state.hands[player_id]) == 0:
            self.state.ended = True
            self.state.winner_id = player_id
            self._push_log(f"{self._player_name(player_id)} wins!")
        return True, ""

    def _resolve_reaction_if_ready(self) -> None:
        ids = set(self.state.player_ids())
        responded = set(self.state.reaction_event.responses.keys())
        if responded == ids or self.state.reaction_event.deadline_passed():
            self._resolve_reaction_final()

    def _resolve_reaction_final(self) -> None:
        if not self.state.reaction_event.active:
            return
        responses = self.state.reaction_event.responses
        players = self.state.player_ids()
        non_responders = [pid for pid in players if pid not in responses]
        losers: list[str] = []
        if non_responders:
            losers = non_responders
        else:
            latest_time = max(responses.values())
            losers = [pid for pid, ts in responses.items() if ts == latest_time]
        for pid in losers:
            for _ in range(2):
                c = self._draw_card_or_rebuild()
                if c is not None:
                    self.state.hands[pid].append(c)
        self.state.reaction_event.active = False
        self._push_log("Reaction result: " + ", ".join(self._player_name(pid) for pid in losers) + " drew 2.")

    def tick(self) -> None:
        if self.state.reaction_event.active and self.state.reaction_event.deadline_passed():
            self._resolve_reaction_final()
        # Cumulative disconnect → remove (works in lobby and in match).
        for p in list(self.state.players):
            if not p.connected and self._cumulative_disconnect(p) >= REMOVE_AFTER_TOTAL_SECONDS:
                self._remove_player(p.player_id, reason="disconnect timeout")
        if not self.state.started or self.state.ended or not self.state.players:
            return
        # If the player who owes a decision is disconnected long enough, auto-pass.
        guard = 0
        while guard < len(self.state.players) + 1:
            guard += 1
            cur_id = self.state.current_player_id()
            cur = self._find_player(cur_id) if cur_id else None
            if cur is None:
                break
            owes = (
                self.state.awaiting_color_for_player == cur_id
                or self.state.awaiting_direction_for_player == cur_id
                or self.state.awaiting_target_for_player == cur_id
                or self.state.may_play_drawn_for_player == cur_id
            )
            it_is_their_turn = owes or self.state.current_player_id() == cur_id
            if not it_is_their_turn:
                break
            if cur.connected:
                break
            if self._current_disconnect_duration(cur) < TURN_SKIP_AFTER_SECONDS:
                break
            # Auto-skip this turn.
            self._auto_skip_turn(cur)
            if self.state.ended:
                break

    def _auto_skip_turn(self, p: Player) -> None:
        # Clear any pending decisions belonging to this player; treat as a forfeit
        # of this round only (their hand is preserved).
        if self.state.awaiting_color_for_player == p.player_id:
            # Default to current_color (no change).
            self.state.awaiting_color_for_player = None
            self.state.awaiting_played_card = None
        if self.state.awaiting_direction_for_player == p.player_id:
            self.state.awaiting_direction_for_player = None
            self.state.awaiting_played_card = None
        if self.state.awaiting_target_for_player == p.player_id:
            self.state.awaiting_target_for_player = None
            self.state.awaiting_played_card = None
        if self.state.may_play_drawn_for_player == p.player_id:
            self.state.may_play_drawn_for_player = None
        # If a draw penalty is pending, the disconnected player eats it on skip.
        if self.state.pending_penalty > 0:
            for _ in range(self.state.pending_penalty):
                c = self._draw_card_or_rebuild()
                if c is not None:
                    self.state.hands[p.player_id].append(c)
            self.state.pending_penalty = 0
            self.state.pending_penalty_min = 0
        self._push_log(f"{p.name} missed turn (disconnected).")
        self.state.next_turn()
