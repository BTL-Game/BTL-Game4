from __future__ import annotations

from typing import Callable
from uuid import uuid4
import random
import time

from src.core.actions import AddBot, DrawCard
from src.ai.simple_bot import SimpleBot

from src.core.engine import GameEngine
from src.core.game_state import GameStateView, to_view


class LocalNetwork:
    def __init__(self) -> None:
        self.engine = GameEngine()
        self._state_callbacks: list[Callable[[str, GameStateView], None]] = []
        self.bots: dict[str, SimpleBot] = {}
        self.bot_ready_at: dict[tuple[str, str], float] = {}

    def host_room(self, player_name: str) -> str:
        player_id = uuid4().hex[:8]
        self.engine.create_room(player_id, player_name)
        self._broadcast_all()
        return player_id

    def join_room(self, room_code: str, player_name: str) -> str:
        del room_code
        player_id = uuid4().hex[:8]
        if not self.engine.join_room(player_id, player_name):
            return ""
        self._broadcast_all()
        return player_id

    def send(self, player_id: str, action: object) -> tuple[bool, str]:
        # Special-case AddBot: create a bot player locally
        if isinstance(action, AddBot):
            requester = next((p for p in self.engine.state.players if p.player_id == player_id), None)
            if requester is None or not requester.is_host:
                return False, "Only host can add bots"
            if self.engine.state.started:
                return False, "Match already started"
            if len(self.engine.state.players) >= 4:
                return False, "Room is full"
            existing = [p.name for p in self.engine.state.players if p.name.startswith("Bot ")]
            nums = set()
            for name in existing:
                try:
                    nums.add(int(name.split(" ")[1]))
                except Exception:
                    continue
            n = 1
            while n in nums:
                n += 1
            bot_name = f"Bot {n}"
            bot_id = uuid4().hex[:8]
            if not self.engine.join_room(bot_id, bot_name):
                return False, "join failed"
            self.bots[bot_id] = SimpleBot()
            self._clear_bot_timers_for(bot_id)
            self._broadcast_all()
            return True, ""

        ok, reason = self.engine.handle_action(player_id, action)
        self._broadcast_all()
        return ok, reason

    def on_state(self, callback: Callable[[str, GameStateView], None]) -> None:
        self._state_callbacks.append(callback)

    def _broadcast_all(self) -> None:
        for p in self.engine.state.players:
            view = to_view(self.engine.state, p.player_id, self.engine.log)
            for cb in self._state_callbacks:
                cb(p.player_id, view)

    def update(self) -> None:
        now = time.monotonic()
        self.engine.tick()
        cur_id = self.engine.state.current_player_id()
        if cur_id is not None and cur_id in self.bots and not self.engine.state.ended:
            if self.engine.state.reaction_event.active:
                stage = "reaction"
            elif self.engine.state.awaiting_color_for_player == cur_id:
                stage = "color"
            elif self.engine.state.awaiting_direction_for_player == cur_id:
                stage = "direction"
            elif self.engine.state.awaiting_target_for_player == cur_id:
                stage = "target"
            else:
                stage = "action"
            ready_key = (cur_id, stage)
            ready_at = self.bot_ready_at.get(ready_key)
            if ready_at is None:
                self.bot_ready_at[ready_key] = now + self._bot_delay_for_stage(stage)
            elif now >= ready_at:
                bot = self.bots[cur_id]
                view = to_view(self.engine.state, cur_id, self.engine.log)
                if stage == "reaction":
                    action = bot.reaction(view, cur_id, delay=False)
                elif stage == "color":
                    action = bot.choose_color(view, cur_id, delay=False)
                elif stage == "direction":
                    action = bot.choose_direction(view, cur_id, delay=False)
                elif stage == "target":
                    action = bot.choose_target(view, cur_id, delay=False)
                else:
                    action = bot.choose_action(view, cur_id, delay=False)
                self.bot_ready_at.pop(ready_key, None)
                ok, _ = self.engine.handle_action(cur_id, action)
                if not ok:
                    if stage == "action":
                        draw_ok, _ = self.engine.handle_action(cur_id, DrawCard())
                        if not draw_ok:
                            self.bot_ready_at[ready_key] = now + self._bot_delay_for_stage(stage)
                    else:
                        self.bot_ready_at[ready_key] = now + random.uniform(0.2, 0.5)
        self._broadcast_all()

    def _clear_bot_timers_for(self, player_id: str) -> None:
        for key in list(self.bot_ready_at.keys()):
            if key[0] == player_id:
                self.bot_ready_at.pop(key, None)

    def _bot_delay_for_stage(self, stage: str) -> float:
        if stage == "action":
            return random.uniform(5.0, 10.0)
        if stage == "reaction":
            return random.uniform(0.8, 2.2)
        return random.uniform(0.4, 1.0)
