from __future__ import annotations

import random
import string
import time

from .actions import (
    ChooseColor,
    ChooseDirection,
    ChooseTarget,
    DeclareUno,
    DrawCard,
    EndTurn,
    HoldBomb,
    KickPlayer,
    LeaveRoom,
    PassBomb,
    PlayCard,
    Reaction,
    StartMatch,
)


TURN_SKIP_AFTER_SECONDS = 30.0
REMOVE_AFTER_TOTAL_SECONDS = 60.0
ASIAN_BOMB_MIN_TURNS = 8
ASIAN_BOMB_MAX_TURNS = 12
ASIAN_BOMB_COUNTDOWN_MIN = 1
ASIAN_BOMB_COUNTDOWN_MAX = 2
from .cards import Card, CardType, Color
from .deck import Deck, build_asian_uno_deck, build_standard_uno_deck
from .events import EventBus
from .game_state import GameState
from .modes import MODE_ASIAN, MODE_BASIC, VALID_MODES
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

    def create_room(self, host_id: str, host_name: str, mode: str = MODE_BASIC) -> None:
        self.state = GameState()
        self.state.mode = mode if mode in VALID_MODES else MODE_BASIC
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
        self.state.uno_declared.clear()
        if self.state.mode == MODE_ASIAN:
            self.state.draw_pile = Deck(cards=build_asian_uno_deck())
        else:
            self.state.draw_pile = Deck(cards=build_standard_uno_deck())
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
        if self.state.mode == MODE_ASIAN:
            self.state.turn_play_count = 0
            self.state.turn_action_card = None
            self.state.turn_color = None
            self.state.bomb_holder_id = None
            self.state.bomb_countdown = 0
            self.state.bomb_penalty = 0
            self.state.bomb_spawn_in = random.randint(ASIAN_BOMB_MIN_TURNS, ASIAN_BOMB_MAX_TURNS)
            self.state.bomb_decision_player_id = None
            self._start_new_turn_asian()
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
        if isinstance(action, DeclareUno):
            return self._handle_declare_uno(player_id)
        if self.state.reaction_event.active:
            return False, "Only reaction input is allowed now"
        if self.state.current_player_id() != player_id:
            return False, "Not your turn"
        if self.state.mode == MODE_ASIAN and self.state.bomb_decision_player_id == player_id:
            if isinstance(action, HoldBomb):
                return self._handle_hold_bomb(player_id)
            if isinstance(action, PassBomb):
                return self._handle_pass_bomb(player_id)
            return False, "Resolve bomb first"
        if isinstance(action, DrawCard):
            return self._handle_draw(player_id)
        if isinstance(action, PlayCard):
            return self._handle_play(player_id, action)
        if isinstance(action, EndTurn):
            return self._handle_end_turn(player_id)
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

    def _handle_declare_uno(self, player_id: str) -> tuple[bool, str]:
        hand_size = len(self.state.hands.get(player_id, []))
        if hand_size != 2:
            return False, f"Can only declare UNO with exactly 2 cards (you have {hand_size})"
        self.state.uno_declared[player_id] = True
        self._push_log(f"{self._player_name(player_id)} declared UNO!")
        return True, ""

    def _handle_draw(self, player_id: str) -> tuple[bool, str]:
        if self.state.mode == MODE_ASIAN:
            return self._handle_draw_asian(player_id)
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

    # ------------------------------------------------------------------
    # Asian mode helpers
    # ------------------------------------------------------------------
    def _is_card_playable_asian(self, card: Card) -> bool:
        if card.card_type in (CardType.WILD, CardType.WILD_DRAW_FOUR):
            return False
        if self.state.turn_color is not None and card.color == self.state.turn_color:
            return True
        top = self.state.top_card
        if top is None:
            return True
        if card.card_type == CardType.NUMBER and top.card_type == CardType.NUMBER and card.value == top.value:
            return True
        if card.card_type == top.card_type and card.card_type != CardType.NUMBER:
            return True
        return False

    def _has_playable_asian(self, player_id: str) -> bool:
        return any(self._is_card_playable_asian(c) for c in self.state.hands.get(player_id, []))

    def _start_new_turn_asian(self) -> None:
        self.state.turn_play_count = 0
        self.state.turn_action_card = None
        self.state.turn_color = random.choice([Color.RED, Color.GREEN, Color.BLUE, Color.YELLOW])
        self.state.bomb_decision_player_id = None
        if not self.state.bomb_holder_id:
            self.state.bomb_spawn_in -= 1
            if self.state.bomb_spawn_in <= 0:
                self._spawn_bomb()
        if self.state.bomb_holder_id == self.state.current_player_id():
            self.state.bomb_decision_player_id = self.state.bomb_holder_id

    def _advance_turn_asian(self, skip_count: int = 0) -> None:
        if not self.state.players:
            return
        # Skip N players, applying bomb-hold defaults if needed.
        for _ in range(skip_count):
            self.state.next_turn()
            skipped_id = self.state.current_player_id()
            if skipped_id and skipped_id == self.state.bomb_holder_id:
                self._apply_bomb_hold(skipped_id, auto=True)
                self._maybe_explode_bomb(skipped_id)
        self.state.next_turn()
        self._start_new_turn_asian()

    def _spawn_bomb(self) -> None:
        if not self.state.players:
            return
        holder = random.choice(self.state.players).player_id
        self.state.bomb_holder_id = holder
        self.state.bomb_countdown = random.randint(ASIAN_BOMB_COUNTDOWN_MIN, ASIAN_BOMB_COUNTDOWN_MAX)
        self.state.bomb_penalty = 1
        self.state.bomb_spawn_in = random.randint(ASIAN_BOMB_MIN_TURNS, ASIAN_BOMB_MAX_TURNS)
        self._push_log(f"Bomb spawned for {self._player_name(holder)}.")

    def _apply_bomb_hold(self, player_id: str, auto: bool = False) -> None:
        if self.state.bomb_holder_id != player_id:
            return
        self.state.bomb_countdown = max(0, self.state.bomb_countdown - 1)
        self.state.bomb_penalty = max(1, self.state.bomb_penalty * 2)
        if auto:
            self._push_log(f"{self._player_name(player_id)} held the bomb (auto).")
        else:
            self._push_log(f"{self._player_name(player_id)} held the bomb.")

    def _apply_bomb_pass(self, player_id: str) -> None:
        if self.state.bomb_holder_id != player_id:
            return
        c = self._draw_card_or_rebuild()
        if c is not None:
            self.state.hands[player_id].append(c)
        self._push_log(f"{self._player_name(player_id)} passed the bomb and drew 1.")
        self.state.bomb_countdown = max(0, self.state.bomb_countdown - 1)
        self.state.bomb_penalty = max(1, self.state.bomb_penalty * 2)
        # Pass to the next player in direction order.
        next_id = self._next_player_id(1)
        if next_id is not None:
            self.state.bomb_holder_id = next_id

    def _maybe_explode_bomb(self, player_id: str) -> None:
        if self.state.bomb_holder_id != player_id:
            return
        if self.state.bomb_countdown > 0:
            return
        penalty = max(0, self.state.bomb_penalty)
        for _ in range(penalty):
            c = self._draw_card_or_rebuild()
            if c is not None:
                self.state.hands[player_id].append(c)
        self._push_log(f"Bomb exploded on {self._player_name(player_id)} (+{penalty}).")
        self.state.bomb_holder_id = None
        self.state.bomb_countdown = 0
        self.state.bomb_penalty = 0
        self.state.bomb_decision_player_id = None

    def _next_player_id(self, step: int = 1) -> str | None:
        if not self.state.players:
            return None
        idx = self.state.turn_index
        new_idx = (idx + self.state.direction * step) % len(self.state.players)
        return self.state.players[new_idx].player_id

    def _handle_play(self, player_id: str, action: PlayCard) -> tuple[bool, str]:
        if self.state.mode == MODE_ASIAN:
            return self._handle_play_asian(player_id, action)
        result = self.rules.validate_play(self.state, player_id, action)
        if not result.ok:
            return False, result.reason
        self.state.may_play_drawn_for_player = None
        hand = self.state.hands[player_id]
        
        # Check UNO violation: if player has 2 cards and didn't declare UNO
        if len(hand) == 2 and not self.state.uno_declared.get(player_id, False):
            self._push_log(f"{self._player_name(player_id)} forgot to declare UNO! +2 penalty cards.")
            for _ in range(2):
                c = self._draw_card_or_rebuild()
                if c is not None:
                    self.state.hands[player_id].append(c)
            # Validate if the action is still valid after penalty
            result = self.rules.validate_play(self.state, player_id, action)
            if not result.ok:
                return False, "Card no longer playable after UNO penalty"
            hand = self.state.hands[player_id]
        
        card = hand.pop(action.hand_index)
        self.state.discard_pile.append(card)
        self.state.top_card = card
        self.state.current_color = card.color if card.color != Color.WILD else self.state.current_color
        self._push_log(f"{self._player_name(player_id)} played {card.code()}.")
        # Reset UNO declaration after playing
        self.state.uno_declared[player_id] = False
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

    def _handle_draw_asian(self, player_id: str) -> tuple[bool, str]:
        if self.state.turn_play_count > 0:
            return False, "Cannot draw after playing; end your turn"
        if self._has_playable_asian(player_id):
            return False, "You have a playable card"
        # Draw until a playable card appears or the deck is exhausted.
        while True:
            c = self._draw_card_or_rebuild()
            if c is None:
                self._push_log("Draw pile empty; turn passes.")
                return self._finish_turn_asian(player_id)
            self.state.hands[player_id].append(c)
            if self._is_card_playable_asian(c):
                # Forced play of the drawn card.
                idx = len(self.state.hands[player_id]) - 1
                return self._handle_play_asian(player_id, PlayCard(hand_index=idx), forced=True)

    def _handle_play_asian(self, player_id: str, action: PlayCard, forced: bool = False) -> tuple[bool, str]:
        result = self.rules.validate_play(self.state, player_id, action)
        if not result.ok:
            return False, result.reason
        self.state.may_play_drawn_for_player = None
        hand = self.state.hands[player_id]
        if len(hand) == 2 and not self.state.uno_declared.get(player_id, False):
            self._push_log(f"{self._player_name(player_id)} forgot to declare UNO! +2 penalty cards.")
            for _ in range(2):
                c = self._draw_card_or_rebuild()
                if c is not None:
                    self.state.hands[player_id].append(c)
            result = self.rules.validate_play(self.state, player_id, action)
            if not result.ok:
                return False, "Card no longer playable after UNO penalty"
            hand = self.state.hands[player_id]

        card = hand.pop(action.hand_index)
        self.state.discard_pile.append(card)
        self.state.top_card = card
        self._push_log(f"{self._player_name(player_id)} played {card.code()}.")
        self.state.uno_declared[player_id] = False

        self.state.turn_play_count += 1
        if card.card_type in (CardType.SKIP, CardType.REVERSE, CardType.DRAW_TWO):
            self.state.turn_action_card = card

        if self.state.turn_play_count >= self.state.turn_play_limit:
            return self._finish_turn_asian(player_id)
        if not self._has_playable_asian(player_id):
            return self._finish_turn_asian(player_id)
        if forced:
            return True, ""
        return True, ""

    def _handle_end_turn(self, player_id: str) -> tuple[bool, str]:
        if self.state.mode != MODE_ASIAN:
            return False, "EndTurn only available in Asian mode"
        if self.state.turn_play_count == 0:
            if self._has_playable_asian(player_id):
                return False, "Play a card or draw"
            can_draw = len(self.state.draw_pile) > 0 or len(self.state.discard_pile) > 1
            if can_draw:
                return False, "Must draw when no playable card"
        return self._finish_turn_asian(player_id)

    def _handle_hold_bomb(self, player_id: str) -> tuple[bool, str]:
        if self.state.mode != MODE_ASIAN:
            return False, "Bomb not available in this mode"
        if self.state.bomb_holder_id != player_id:
            return False, "You are not holding the bomb"
        self._apply_bomb_hold(player_id)
        self.state.bomb_decision_player_id = None
        return True, ""

    def _handle_pass_bomb(self, player_id: str) -> tuple[bool, str]:
        if self.state.mode != MODE_ASIAN:
            return False, "Bomb not available in this mode"
        if self.state.bomb_holder_id != player_id:
            return False, "You are not holding the bomb"
        self._apply_bomb_pass(player_id)
        self.state.bomb_decision_player_id = None
        return True, ""

    def _finish_turn_asian(self, player_id: str) -> tuple[bool, str]:
        action = self.state.turn_action_card
        skip_count = 0
        if action is not None:
            if action.card_type == CardType.REVERSE:
                self.state.direction *= -1
                if len(self.state.players) == 2:
                    skip_count = 1
            elif action.card_type == CardType.SKIP:
                skip_count = 1
            elif action.card_type == CardType.DRAW_TWO:
                target_id = self._next_player_id(1)
                if target_id is not None:
                    for _ in range(2):
                        c = self._draw_card_or_rebuild()
                        if c is not None:
                            self.state.hands[target_id].append(c)
                    self._push_log(f"{self._player_name(target_id)} drew 2 cards.")
                skip_count = 1

        # Bomb check at end of this player's turn.
        self._maybe_explode_bomb(player_id)

        # Win check happens after bomb resolution.
        self._check_win_then_continue(player_id)
        if self.state.ended:
            if self.state.bomb_holder_id == player_id:
                self.state.bomb_holder_id = None
                self.state.bomb_countdown = 0
                self.state.bomb_penalty = 0
                self.state.bomb_decision_player_id = None
            return True, ""

        self._advance_turn_asian(skip_count=skip_count)
        return True, ""

    def _handle_choose_color(self, player_id: str, action: ChooseColor) -> tuple[bool, str]:
        if self.state.mode == MODE_ASIAN:
            return False, "Color choice not used in Asian mode"
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
        if self.state.mode == MODE_ASIAN:
            return False, "Direction choice not used in Asian mode"
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
        if self.state.mode == MODE_ASIAN:
            return False, "Target choice not used in Asian mode"
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
            if self.state.mode == MODE_ASIAN and self.state.bomb_holder_id == player_id:
                self.state.bomb_holder_id = None
                self.state.bomb_countdown = 0
                self.state.bomb_penalty = 0
                self.state.bomb_decision_player_id = None
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
                or (self.state.mode == MODE_ASIAN and self.state.bomb_decision_player_id == cur_id)
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
        if self.state.mode == MODE_ASIAN:
            if self.state.bomb_decision_player_id == p.player_id:
                self._apply_bomb_hold(p.player_id, auto=True)
                self.state.bomb_decision_player_id = None
            self._push_log(f"{p.name} missed turn (disconnected).")
            self._finish_turn_asian(p.player_id)
            return
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
