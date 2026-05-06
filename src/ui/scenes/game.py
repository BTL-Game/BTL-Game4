from __future__ import annotations

import math
import time

import pygame

from src.core.actions import (
    ChooseColor,
    ChooseDirection,
    ChooseTarget,
    DrawCard,
    EndTurn,
    HoldBomb,
    PlayCard,
    PassBomb,
    Reaction,
    DeclareUno,
)
from src.core.cards import CardType, Color
from src.ui.scene import AppContext, Scene
from src.ui.theme import (
    ACCENT,
    BG,
    BG_DARK,
    BLUE,
    CARD_H,
    CARD_W,
    GREEN,
    MUTED,
    PANEL,
    RED,
    SCREEN_H,
    SCREEN_W,
    TEXT,
    YELLOW,
)
from src.ui.widgets import Button


COLOR_RGB = {
    Color.RED: RED,
    Color.GREEN: GREEN,
    Color.BLUE: BLUE,
    Color.YELLOW: YELLOW,
}

_DEAL_OPP_DELAY = 80  # ms between opponent deal card animations


class GameScene(Scene):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__(ctx)
        self.font = pygame.font.SysFont("arial", 16)
        self.font_b = pygame.font.SysFont("arial", 18, bold=True)
        self.font_big = pygame.font.SysFont("arial", 30, bold=True)
        self.font_huge = pygame.font.SysFont("arialblack,arial", 48, bold=True)
        self.draw_btn = Button(pygame.Rect(24, SCREEN_H - 78, 160, 56), "DRAW")
        self.end_turn_btn = Button(pygame.Rect(200, SCREEN_H - 78, 160, 56), "END TURN")
        self.uno_btn = Button(pygame.Rect(SCREEN_W - 196, SCREEN_H - 86, 172, 72), "UNO!")
        self.react_btn = Button(pygame.Rect(SCREEN_W // 2 - 80, SCREEN_H // 2 + 110, 160, 54), "REACT!")
        self.hold_bomb_btn = Button(pygame.Rect(SCREEN_W // 2 - 170, SCREEN_H // 2 + 120, 150, 52), "HOLD")
        self.pass_bomb_btn = Button(pygame.Rect(SCREEN_W // 2 + 20, SCREEN_H // 2 + 120, 150, 52), "PASS")
        self.leave_btn = Button(pygame.Rect(24, 18, 72, 32), "LEAVE")
        self.effects: list[dict] = []
        self._last_effect_key = ""
        self.card_rects: list[tuple[int, pygame.Rect]] = []
        self.color_rects: list[tuple[Color, pygame.Rect]] = []
        self.target_rects: list[tuple[str, pygame.Rect]] = []
        self.dir_cw_rect = pygame.Rect(0, 0, 0, 0)
        self.dir_ccw_rect = pygame.Rect(0, 0, 0, 0)
        self.draw_pile_rect = pygame.Rect(0, 0, 0, 0)
        self.sound_btn_rect = pygame.Rect(SCREEN_W - 78, 18, 30, 30)
        self.music_btn_rect = pygame.Rect(SCREEN_W - 42, 18, 30, 30)
        # Chat UI
        self.chat_panel = pygame.Rect(SCREEN_W - 312, 84, 292, 260)
        self.chat_toggle_btn = Button(pygame.Rect(SCREEN_W - 58, 84, 42, 42), "💬")
        self.chat_input_rect = pygame.Rect(
            self.chat_panel.x + 12,
            self.chat_panel.bottom - 40,
            self.chat_panel.width - 24,
            30,
        )
        # Deal animation state
        self._deal_active = False
        self._deal_start_ms = 0
        self._deal_hand_size = 0
        self._deal_done = False
        self._deal_opp_sizes: list[tuple[tuple[int, int], int]] = []  # (center_xy, n_cards)
        # Track real state changes so sounds/effects only run after the engine accepts a play.
        self._last_top_card_code: str | None = None
        self._last_log_snapshot: tuple[str, ...] | None = None
        self._last_player_card_counts: dict[str, int] = {}
        self._last_turn_player_id: str | None = None

        # Flying card overlays used to show who just played which card.
        self.play_animations: list[dict] = []

        # Local UNO declaration state (client-side indicator)
        self.uno_declared: bool = False
        self.uno_declared_until: int = 0

    def _has_playable_card(self, view) -> bool:
        """Check if the player has at least one playable card in their hand."""
        try:
            if view is None or view.self_hand is None or view.top_card is None:
                return False
            if getattr(view, "mode", "basic") == "asian":
                turn_color = getattr(view, "turn_color", None)
                for card in view.self_hand:
                    if card.card_type in (CardType.WILD, CardType.WILD_DRAW_FOUR):
                        continue
                    if turn_color is not None and card.color == turn_color:
                        return True
                    top = view.top_card
                    if top is None:
                        return True
                    if (
                        card.card_type == CardType.NUMBER
                        and top.card_type == CardType.NUMBER
                        and card.value == top.value
                    ):
                        return True
                    if card.card_type == top.card_type and card.card_type != CardType.NUMBER:
                        return True
                return False
            for card in view.self_hand:
                if card.card_type in (CardType.WILD, CardType.WILD_DRAW_FOUR):
                    return True
                if card.color == view.current_color:
                    return True
                if (
                    card.card_type == CardType.NUMBER
                    and view.top_card.card_type == CardType.NUMBER
                    and card.value == view.top_card.value
                ):
                    return True
                if card.card_type == view.top_card.card_type and card.card_type != CardType.NUMBER:
                    return True
            return False
        except Exception:
            return False

    def update(self, dt: float) -> None:
        # Keep the temporary visual effects list small even if the window is idle.
        del dt
        now = pygame.time.get_ticks()
        self.effects = [fx for fx in self.effects if now - fx["created"] <= fx["duration"]]
        self.play_animations = [
            anim for anim in self.play_animations
            if now - anim["created"] <= anim["duration"]
        ]

        view = self.ctx.current_view
        if view is not None:
            # Trigger deal animation once per game start.
            if view.started and not self._deal_done and not self._deal_active:
                n = len(view.self_hand)
                if n > 0:
                    self._deal_active = True
                    self._deal_start_ms = now
                    self._deal_hand_size = n
                    # Gather opponent positions for their deal animation.
                    others = [p for p in view.players if p.player_id != self.ctx.player_id]
                    slots = []
                    if len(others) == 1:
                        slots = [(SCREEN_W // 2, 122)]
                    elif len(others) == 2:
                        slots = [(124, SCREEN_H // 2 - 38), (SCREEN_W - 124, SCREEN_H // 2 - 38)]
                    elif len(others) >= 3:
                        slots = [(124, SCREEN_H // 2 - 38), (SCREEN_W // 2, 122),
                                 (SCREEN_W - 124, SCREEN_H // 2 - 38)]
                    self._deal_opp_sizes = [(s, p.card_count) for s, p in zip(slots, others)]

            # Expire deal animation.
            if self._deal_active:
                total_ms = (self._deal_hand_size - 1) * 120 + 400
                if now - self._deal_start_ms > total_ms:
                    self._deal_active = False
                    self._deal_done = True

            # Spawn play visuals/sounds from accepted engine state, not from raw clicks.
            self._sync_play_feedback(view)

    # ------------------------------------------------------------------
    # input
    # ------------------------------------------------------------------
    def handle_event(self, event: pygame.event.Event) -> None:
        view = self.ctx.current_view
        if view is None:
            return

        if self._handle_audio_toggle(event):
            return

        # Leave game button (always active).
        if self.leave_btn.clicked(event):
            if hasattr(self.ctx, "leave_game") and callable(self.ctx.leave_game):
                self.ctx.leave_game()
            return

        # Reaction event takes priority over gameplay/chat input.
        if view.reaction_active:
            if self.react_btn.clicked(event):
                self.ctx.assets.play_sound("assets/sounds/cardplay_3.mp3")
                self.ctx.network.send(self.ctx.player_id, Reaction())
            return

        # Bomb decision (Asian mode) takes priority.
        if getattr(view, "mode", "basic") == "asian" and view.bomb_decision_player_id == self.ctx.player_id:
            if self.hold_bomb_btn.clicked(event):
                self.ctx.network.send(self.ctx.player_id, HoldBomb())
                return
            if self.pass_bomb_btn.clicked(event):
                self.ctx.network.send(self.ctx.player_id, PassBomb())
                return
            return

        # Color picker modal.
        if view.awaiting_color_for_player == self.ctx.player_id:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                for col, rect in self.color_rects:
                    if rect.collidepoint(event.pos):
                        self.ctx.network.send(self.ctx.player_id, ChooseColor(col))
                        return
            if event.type == pygame.KEYDOWN:
                m = {pygame.K_r: Color.RED, pygame.K_g: Color.GREEN,
                     pygame.K_b: Color.BLUE, pygame.K_y: Color.YELLOW}
                if event.key in m:
                    self.ctx.network.send(self.ctx.player_id, ChooseColor(m[event.key]))
            return

        # Direction picker (Rule 0).
        if view.awaiting_direction_for_player == self.ctx.player_id:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.dir_cw_rect.collidepoint(event.pos):
                    self.ctx.network.send(self.ctx.player_id, ChooseDirection(1))
                elif self.dir_ccw_rect.collidepoint(event.pos):
                    self.ctx.network.send(self.ctx.player_id, ChooseDirection(-1))
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_c:
                    self.ctx.network.send(self.ctx.player_id, ChooseDirection(1))
                if event.key == pygame.K_v:
                    self.ctx.network.send(self.ctx.player_id, ChooseDirection(-1))
            return

        # Target picker (Rule 7).
        if view.awaiting_target_for_player == self.ctx.player_id:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                for pid, rect in self.target_rects:
                    if rect.collidepoint(event.pos):
                        self.ctx.network.send(self.ctx.player_id, ChooseTarget(pid))
                        return
            if event.type == pygame.KEYDOWN:
                others = [p for p in view.players if p.player_id != self.ctx.player_id]
                idx = event.key - pygame.K_1
                if 0 <= idx < len(others):
                    self.ctx.network.send(self.ctx.player_id, ChooseTarget(others[idx].player_id))
            return

        if self._handle_chat_event(event):
            return

        # Normal play.
        if self.draw_btn.clicked(event):
            self._play_draw_sound()
            self.ctx.network.send(self.ctx.player_id, DrawCard())
            return
        if getattr(view, "mode", "basic") == "asian" and self.end_turn_btn.clicked(event):
            self.ctx.network.send(self.ctx.player_id, EndTurn())
            return
        if self.uno_btn.clicked(event):
            self.ctx.assets.play_sound("assets/sounds/cardplay_3.mp3")
            try:
                hand_len = len(view.self_hand) if view.self_hand is not None else 0
            except Exception:
                hand_len = 0
            if hand_len == 2:
                try:
                    if hasattr(self.ctx, "network") and hasattr(self.ctx.network, "send"):
                        self.ctx.network.send(self.ctx.player_id, DeclareUno())
                        now = pygame.time.get_ticks()
                        self.uno_declared = True
                        self.uno_declared_until = now + 5000
                        if isinstance(self.ctx.toasts, list):
                            self.ctx.toasts.append(("UNO!", time.monotonic() + 1.4))
                    else:
                        print("[WARN] network interface not available for DeclareUno")
                except Exception:
                    import traceback

                    print("[ERROR] Exception while sending DeclareUno:")
                    traceback.print_exc()
            elif isinstance(self.ctx.toasts, list):
                self.ctx.toasts.append(("UNO needs exactly 2 cards", time.monotonic() + 1.4))
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.draw_pile_rect.collidepoint(event.pos):
                self._play_draw_sound()
                self.ctx.network.send(self.ctx.player_id, DrawCard())
                return
            for idx, rect in self.card_rects:
                if rect.collidepoint(event.pos):
                    # Do not play sound/effects here. The engine may reject the card.
                    # Feedback is triggered in update() after the public state/log confirms a play.
                    self.ctx.network.send(self.ctx.player_id, PlayCard(hand_index=idx))
                    return

    # ------------------------------------------------------------------
    # play feedback from confirmed state
    # ------------------------------------------------------------------
    def _sync_play_feedback(self, view) -> None:
        """Trigger card-play animation/sound only after the public state confirms it."""
        top = view.top_card
        top_code = top.code() if top is not None else None
        current_counts = {p.player_id: p.card_count for p in view.players}
        log_snapshot = tuple(view.log or [])

        # First view after entering the scene is just baseline state.
        if self._last_log_snapshot is None:
            self._last_log_snapshot = log_snapshot
            self._last_player_card_counts = current_counts
            self._last_turn_player_id = view.turn_player_id
            self._last_top_card_code = top_code
            return

        play_name: str | None = None
        play_code: str | None = None
        new_lines = self._new_log_lines(self._last_log_snapshot, log_snapshot)
        for line in reversed(new_lines):
            parsed = self._parse_play_log(line)
            if parsed is None:
                continue
            name, code = parsed
            if top_code is None or code == top_code:
                play_name = name
                play_code = code
                break

        should_feedback = False
        if play_code is not None and top is not None:
            should_feedback = True
        elif top_code != self._last_top_card_code:
            # Fallback for a state refresh where the play log was truncated/missed.
            should_feedback = self._last_top_card_code is not None and top is not None

        if should_feedback and top is not None:
            actor_id = self._player_id_from_name(view, play_name) if play_name else None
            if actor_id is None:
                actor_id = self._infer_play_actor_id(view, current_counts)
            if play_name is None:
                play_name = self._player_name_from_id(view, actor_id)
            self._register_play_feedback(view, actor_id, play_name, top)

        self._last_log_snapshot = log_snapshot
        self._last_player_card_counts = current_counts
        self._last_turn_player_id = view.turn_player_id
        self._last_top_card_code = top_code

    def _new_log_lines(self, old: tuple[str, ...], new: tuple[str, ...]) -> list[str]:
        if old == new:
            return []
        max_overlap = min(len(old), len(new))
        for overlap in range(max_overlap, 0, -1):
            if old[-overlap:] == new[:overlap]:
                return list(new[overlap:])
        return list(new)

    def _parse_play_log(self, line: str) -> tuple[str, str] | None:
        marker = " played "
        if marker not in line or not line.endswith("."):
            return None
        name, code = line[:-1].rsplit(marker, 1)
        if not name or not code:
            return None
        return name, code

    def _player_id_from_name(self, view, name: str | None) -> str | None:
        if not name:
            return None
        for p in view.players:
            if p.name == name:
                return p.player_id
        return None

    def _player_name_from_id(self, view, player_id: str | None) -> str:
        if player_id == self.ctx.player_id:
            return "You"
        for p in view.players:
            if p.player_id == player_id:
                return p.name
        return "Player"

    def _infer_play_actor_id(self, view, current_counts: dict[str, int]) -> str | None:
        decreased: list[str] = []
        for pid, count in current_counts.items():
            prev = self._last_player_card_counts.get(pid)
            if prev is not None and count < prev:
                decreased.append(pid)
        if len(decreased) == 1:
            return decreased[0]
        if self._last_turn_player_id in decreased:
            return self._last_turn_player_id
        return self._last_turn_player_id or view.turn_player_id

    def _discard_center(self) -> tuple[int, int]:
        cx, cy = SCREEN_W // 2, SCREEN_H // 2 - 6
        return (cx + 42 + CARD_W // 2, cy)

    def _player_card_source_pos(self, view, player_id: str | None) -> tuple[int, int]:
        if player_id == self.ctx.player_id:
            return (SCREEN_W // 2, SCREEN_H - CARD_H // 2 - 38)

        others = [p for p in view.players if p.player_id != self.ctx.player_id]
        slots: list[tuple[str, int, int]] = []
        if len(others) == 1:
            slots = [("top", SCREEN_W // 2, 122)]
        elif len(others) == 2:
            slots = [("left", 124, SCREEN_H // 2 - 38), ("right", SCREEN_W - 124, SCREEN_H // 2 - 38)]
        elif len(others) >= 3:
            slots = [
                ("left", 124, SCREEN_H // 2 - 38),
                ("top", SCREEN_W // 2, 122),
                ("right", SCREEN_W - 124, SCREEN_H // 2 - 38),
            ]
        for (_where, cx, cy), opp in zip(slots, others):
            if opp.player_id == player_id:
                return (cx, cy + 38)
        return (SCREEN_W // 2, 96)

    def _register_play_feedback(self, view, player_id: str | None, player_name: str, card) -> None:
        self._play_card_sound(card)
        self._spawn_card_effect(card)
        start = self._player_card_source_pos(view, player_id)
        end = self._discard_center()
        now = pygame.time.get_ticks()
        display_name = "You" if player_id == self.ctx.player_id else player_name
        self.play_animations.append({
            "card": card,
            "player_name": display_name,
            "start": start,
            "end": end,
            "created": now,
            "duration": 620,
            "angle": -14 if start[0] < end[0] else 14,
        })
        # Keep only recent animations; several cards can be played in Asian mode.
        self.play_animations = self.play_animations[-4:]

    # ------------------------------------------------------------------
    # rendering
    # ------------------------------------------------------------------
    def draw(self, screen: pygame.Surface) -> None:
        view = self.ctx.current_view
        self._draw_background(screen)
        if view is None:
            return

        self._draw_table_oval(screen)
        self._draw_top_bar(screen, view)
        self._draw_opponents(screen, view)
        self._draw_center_piles(screen, view)
        if self._deal_active:
            self._draw_deal_animation(screen, view)
        else:
            self._draw_hand(screen, view)
        self._draw_play_animations(screen)
        self._draw_effects(screen)
        self._draw_log(screen, view)
        self._draw_chat(screen)
        self._draw_buttons(screen, view)

        # Modals on top.
        if view.reaction_active:
            self._draw_reaction(screen, view)
        elif getattr(view, "mode", "basic") == "asian" and view.bomb_decision_player_id == self.ctx.player_id:
            self._draw_bomb_decision(screen, view)
        elif view.awaiting_color_for_player == self.ctx.player_id:
            self._draw_color_picker(screen)
        elif view.awaiting_direction_for_player == self.ctx.player_id:
            self._draw_direction_picker(screen)
        elif view.awaiting_target_for_player == self.ctx.player_id:
            self._draw_target_picker(screen, view)
        else:
            # Hint when waiting for someone else's modal.
            if view.awaiting_color_for_player or view.awaiting_direction_for_player or view.awaiting_target_for_player:
                self._draw_waiting_modal(screen, view)

    def _draw_background(self, screen: pygame.Surface) -> None:
        bg = self.ctx.assets.image_first(
            ["assets/scenes/bg_1.jpg", "assets/scenes/bg_2.jpg", "assets/scenes/bg_1.avif"],
            (SCREEN_W, SCREEN_H),
        )
        if bg is not None:
            screen.blit(bg, (0, 0))
            overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 85))
            screen.blit(overlay, (0, 0))
        else:
            screen.fill(BG)

    def _draw_glass_rect(
        self,
        screen: pygame.Surface,
        rect: pygame.Rect,
        fill=(15, 18, 32, 180),
        border=(145, 120, 255, 120),
        radius: int = 16,
    ) -> None:
        panel = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(panel, fill, panel.get_rect(), border_radius=radius)
        screen.blit(panel, rect.topleft)
        pygame.draw.rect(screen, border, rect, 2, border_radius=radius)

    def _draw_card_shadow(self, screen: pygame.Surface, rect: pygame.Rect, alpha: int = 95) -> None:
        shadow = pygame.Surface((rect.width + 12, rect.height + 12), pygame.SRCALPHA)
        pygame.draw.rect(shadow, (0, 0, 0, alpha), shadow.get_rect(), border_radius=14)
        screen.blit(shadow, (rect.x + 6, rect.y + 8))

    def _draw_table_oval(self, screen: pygame.Surface) -> None:
        table_rect = pygame.Rect(46, 92, SCREEN_W - 92, SCREEN_H - 230)
        # Shadow/rim.
        pygame.draw.ellipse(screen, (28, 13, 8), table_rect.inflate(34, 34))
        pygame.draw.ellipse(screen, (119, 66, 31), table_rect.inflate(18, 18))
        # Felt surface.
        felt = pygame.Surface(table_rect.size, pygame.SRCALPHA)
        pygame.draw.ellipse(felt, (*BG_DARK, 238), felt.get_rect())
        pygame.draw.ellipse(felt, (23, 121, 73, 220), felt.get_rect().inflate(-26, -26), 4)
        pygame.draw.ellipse(felt, (255, 255, 255, 22), felt.get_rect().inflate(-90, -74), 2)
        screen.blit(felt, table_rect.topleft)

    def _draw_top_bar(self, screen: pygame.Surface, view) -> None:
        bar = pygame.Rect(92, 10, SCREEN_W - 184, 58)
        self._draw_glass_rect(screen, bar, fill=(10, 12, 28, 220), border=(145, 100, 255, 170), radius=18)
        turn_name = next((p.name for p in view.players if p.player_id == view.turn_player_id), "?")
        you_turn = view.turn_player_id == self.ctx.player_id
        dir_icon = "↻" if view.direction == 1 else "↺"
        dir_str = "CLOCKWISE" if view.direction == 1 else "COUNTER"
        mode = getattr(view, "mode", "basic")
        col_src = view.turn_color if mode == "asian" else view.current_color
        col = col_src.value.upper() if col_src else "—"
        col_rgb = COLOR_RGB.get(col_src, MUTED)

        items = [
            ("ROOM", view.room_code, 90),
            ("TURN", "YOU" if you_turn else turn_name, 130),
            ("DIR", f"{dir_icon} {dir_str}", 120),
        ]
        if mode == "asian":
            items.extend([
                ("MODE", "ASIAN", 90),
                ("TURN COLOR", col, 140),
                ("PLAYS", f"{view.turn_play_count}/{view.turn_play_limit}", 90),
            ])
            if view.bomb_holder_id:
                if view.bomb_holder_id == self.ctx.player_id:
                    bomb_val = f"YOU {view.bomb_countdown}/{view.bomb_penalty}"
                else:
                    bomb_val = "ACTIVE"
                items.append(("BOMB", bomb_val, 120))
            items.append(("DECK", str(view.draw_count), 70))
        else:
            items.extend([
                ("COLOR", col, 120),
                ("PENDING", f"+{view.pending_penalty}", 130),
                ("DECK", str(view.draw_count), 88),
            ])
        x = bar.x + 18
        for label, value, width in items:
            label_surf = self.font.render(label, True, (190, 170, 255))
            screen.blit(label_surf, (x, bar.y + 7))
            value_color = ACCENT if (label == "TURN" and you_turn) else TEXT
            if label == "PENDING" and view.pending_penalty:
                value_color = (255, 115, 230)
            value_surf = self.font_b.render(value, True, value_color)
            if label in ("COLOR", "TURN COLOR"):
                pygame.draw.circle(screen, col_rgb, (x + 18, bar.y + 38), 13)
                pygame.draw.circle(screen, TEXT, (x + 18, bar.y + 38), 13, 2)
                screen.blit(value_surf, (x + 38, bar.y + 29))
            else:
                screen.blit(value_surf, (x, bar.y + 29))
            x += width
            pygame.draw.line(screen, (255, 255, 255, 45), (x - 14, bar.y + 10), (x - 14, bar.bottom - 10), 1)

        # Local UNO indicator near the top bar when declared recently.
        if self.uno_declared and pygame.time.get_ticks() < self.uno_declared_until:
            tag_rect = pygame.Rect(bar.right - 144, bar.y + 14, 74, 30)
            pygame.draw.rect(screen, (170, 48, 38), tag_rect, border_radius=10)
            pygame.draw.rect(screen, YELLOW, tag_rect, 2, border_radius=10)
            tag = self.font_b.render("UNO!", True, YELLOW)
            screen.blit(tag, tag.get_rect(center=tag_rect.center))

        # Sound/music toggle buttons – styled pill buttons.
        audio_buttons = [
            (self.sound_btn_rect, "🔊" if self.ctx.assets.sound_enabled else "🔇", self.ctx.assets.sound_enabled),
            (self.music_btn_rect, "♫" if self.ctx.assets.music_enabled else "✕", self.ctx.assets.music_enabled),
        ]
        for r, label, active in audio_buttons:
            hover = r.collidepoint(pygame.mouse.get_pos())
            bg_on  = (55, 90, 55) if active else (90, 50, 50)
            bg_hov = (75, 120, 75) if active else (120, 65, 65)
            pygame.draw.rect(screen, bg_hov if hover else bg_on, r, border_radius=9)
            border_col = (120, 220, 120) if active else (220, 120, 120)
            pygame.draw.rect(screen, border_col, r, 2, border_radius=9)
            txt = self.font_b.render(label, True, TEXT)
            screen.blit(txt, txt.get_rect(center=r.center))

    def _draw_opponents(self, screen: pygame.Surface, view) -> None:
        others = [p for p in view.players if p.player_id != self.ctx.player_id]
        slots = []
        if len(others) == 1:
            slots = [("top", SCREEN_W // 2, 122)]
        elif len(others) == 2:
            slots = [("left", 124, SCREEN_H // 2 - 38), ("right", SCREEN_W - 124, SCREEN_H // 2 - 38)]
        elif len(others) >= 3:
            slots = [
                ("left", 124, SCREEN_H // 2 - 38),
                ("top", SCREEN_W // 2, 122),
                ("right", SCREEN_W - 124, SCREEN_H // 2 - 38),
            ]
        for avatar_index, ((where, cx, cy), opp) in enumerate(zip(slots, others)):
            self._draw_opponent(screen, opp, cx, cy, where, opp.player_id == view.turn_player_id, avatar_index)

    def _draw_opponent(self, screen, opp, cx, cy, where, is_turn, avatar_index: int) -> None:
        panel_w = 230 if where == "top" else 190
        panel_h = 126
        panel = pygame.Rect(cx - panel_w // 2, cy - 62, panel_w, panel_h)
        self._draw_glass_rect(
            screen,
            panel,
            fill=(11, 13, 24, 170),
            border=(255, 215, 0, 190) if is_turn and opp.connected else (130, 130, 170, 80),
            radius=18,
        )

        avatar_size = 62
        avatar_paths = [
            f"assets/avatars/{opp.name.lower()}.png",
            f"assets/avatars/{opp.name.lower()}.jpg",
            f"assets/avatars/avt_{avatar_index + 1}.jpg",
            f"assets/avatars/avt_{avatar_index + 1}.png",
            "assets/avatars/default.png",
            "assets/avatars/avt_4.jpg",
        ]
        avatar_file = self.ctx.assets.first_existing(avatar_paths)
        if avatar_file is not None:
            try:
                avatar = self.ctx.assets.circular_image(avatar_file, avatar_size)
                a_rect = avatar.get_rect(center=(cx, panel.y + 36))
                screen.blit(avatar, a_rect)
                pygame.draw.circle(screen, ACCENT if is_turn else (230, 230, 240), a_rect.center, avatar_size // 2 + 3, 3)
            except Exception:
                pass

        name_color = ACCENT if is_turn else TEXT
        if not opp.connected:
            name_color = (170, 170, 170)
        nameplate = pygame.Rect(cx - 70, panel.y + 68, 140, 28)
        pygame.draw.rect(screen, (45, 44, 78), nameplate, border_radius=10)
        pygame.draw.rect(screen, (255, 255, 255, 65), nameplate, 1, border_radius=10)
        name = self.font_b.render(opp.name, True, name_color)
        screen.blit(name, name.get_rect(center=nameplate.center))

        count_badge = pygame.Rect(nameplate.right - 7, nameplate.y - 4, 34, 34)
        pygame.draw.rect(screen, (245, 230, 95), count_badge, border_radius=10)
        pygame.draw.rect(screen, (40, 30, 20), count_badge, 2, border_radius=10)
        count_text = self.font_b.render(str(opp.card_count), True, (30, 25, 20))
        screen.blit(count_text, count_text.get_rect(center=count_badge.center))

        n = max(1, min(opp.card_count, 7))
        mini = (32, 48)
        spacing = 13
        total_w = mini[0] + spacing * (n - 1)
        x0 = cx - total_w // 2
        y = panel.bottom - mini[1] - 4
        for i in range(n):
            card_rect = pygame.Rect(x0 + i * spacing, y, *mini)
            self._draw_card_shadow(screen, card_rect, alpha=45)
            back = self.ctx.assets.card_back(mini)
            if not opp.connected:
                back = back.copy()
                back.set_alpha(110)
            angle = (i - (n - 1) / 2) * 3
            rotated = pygame.transform.rotozoom(back, -angle, 1.0)
            screen.blit(rotated, rotated.get_rect(center=card_rect.center))

        if not opp.connected:
            remain_total = max(0, int(60 - opp.disconnect_seconds))
            remain_skip = max(0, int(30 - opp.disconnect_seconds))
            label = f"OFFLINE: skip {remain_skip}s" if remain_skip > 0 else f"REMOVE {remain_total}s"
            tag = self.font.render(label, True, (255, 160, 120))
            screen.blit(tag, tag.get_rect(center=(cx, panel.bottom + 14)))

    def _draw_center_piles(self, screen: pygame.Surface, view) -> None:
        cx, cy = SCREEN_W // 2, SCREEN_H // 2 - 6
        self.draw_pile_rect = pygame.Rect(cx - CARD_W - 42, cy - CARD_H // 2, CARD_W, CARD_H)
        disc = pygame.Rect(cx + 42, cy - CARD_H // 2, CARD_W, CARD_H)

        for rect in (self.draw_pile_rect, disc):
            self._draw_card_shadow(screen, rect, alpha=125)

        if view.draw_count > 0:
            stack_offsets = [(8, 8), (4, 4), (0, 0)]
            for ox, oy in stack_offsets:
                screen.blit(self.ctx.assets.card_back((CARD_W, CARD_H)), self.draw_pile_rect.move(ox, oy))
        else:
            pygame.draw.rect(screen, BG_DARK, self.draw_pile_rect, border_radius=12)

        if view.top_card is not None:
            surf = self.ctx.assets.card_surface(view.top_card, (CARD_W, CARD_H))
            screen.blit(surf, disc)
            if view.top_card.card_type in (CardType.DRAW_TWO, CardType.WILD_DRAW_FOUR, CardType.REVERSE, CardType.SKIP):
                pygame.draw.rect(screen, ACCENT, disc.inflate(8, 8), 3, border_radius=15)
        else:
            pygame.draw.rect(screen, BG_DARK, disc, border_radius=12)

        for label, rect in (("DRAW", self.draw_pile_rect), ("DISCARD", disc)):
            pill = pygame.Rect(0, 0, 88, 24)
            pill.center = (rect.centerx, rect.bottom + 18)
            self._draw_glass_rect(screen, pill, fill=(0, 0, 0, 135), border=(255, 255, 255, 45), radius=10)
            txt = self.font.render(label, True, TEXT)
            screen.blit(txt, txt.get_rect(center=pill.center))

        if view.pending_penalty:
            txt = self.font_huge.render(f"+{view.pending_penalty}", True, (255, 95, 230))
            screen.blit(txt, txt.get_rect(center=(cx, cy - CARD_H // 2 - 36)))

    def _draw_hand(self, screen: pygame.Surface, view) -> None:
        self.card_rects.clear()
        n = len(view.self_hand)
        if n == 0:
            return
        max_w = SCREEN_W - 270
        spacing = min(CARD_W + 10, max_w // max(1, n))
        total_w = spacing * (n - 1) + CARD_W
        x0 = (SCREEN_W - total_w) // 2
        y = SCREEN_H - CARD_H - 38
        mouse = pygame.mouse.get_pos()
        is_my_turn = view.turn_player_id == self.ctx.player_id
        for idx, card in enumerate(view.self_hand):
            rect = pygame.Rect(x0 + idx * spacing, y, CARD_W, CARD_H)
            hover = rect.collidepoint(mouse)
            if hover:
                rect = rect.move(0, -18)
            self._draw_card_shadow(screen, rect, alpha=95 if hover else 70)
            surf = self.ctx.assets.card_surface(card, (CARD_W, CARD_H))
            screen.blit(surf, rect)
            if is_my_turn and hover:
                pygame.draw.rect(screen, ACCENT, rect.inflate(6, 6), 3, border_radius=14)
            self.card_rects.append((idx, rect))

    def _draw_deal_animation(self, screen: pygame.Surface, view) -> None:
        """Animate cards flying from the draw pile to the player's hand."""
        now = pygame.time.get_ticks()
        n = self._deal_hand_size
        if n == 0:
            return

        FLIGHT_MS = 300
        CARD_DELAY = 120

        # Hand layout (mirrors _draw_hand).
        max_w = SCREEN_W - 270
        spacing = min(CARD_W + 10, max_w // max(1, n))
        total_w = spacing * (n - 1) + CARD_W
        x0 = (SCREEN_W - total_w) // 2
        hand_y = SCREEN_H - CARD_H - 38

        # Deck source centre.
        cx_t, cy_t = SCREEN_W // 2, SCREEN_H // 2 - 6
        deck_cx = cx_t - CARD_W - 42 + CARD_W // 2
        deck_cy = cy_t

        age = now - self._deal_start_ms

        # Opponent cards – just 3 cards each, staggered earlier.
        for (opp_cx, opp_cy), opp_n in self._deal_opp_sizes:
            for k in range(min(opp_n, 4)):
                opp_start = k * _DEAL_OPP_DELAY
                if age < opp_start:
                    break
                card_age = age - opp_start
                t = min(1.0, card_age / FLIGHT_MS)
                t_e = 1 - (1 - t) ** 2
                cur_cx = deck_cx + (opp_cx - deck_cx) * t_e
                cur_cy = deck_cy + (opp_cy - deck_cy) * t_e
                scale = 1.2 - 0.2 * t_e
                w, h = int(CARD_W * scale * 0.55), int(CARD_H * scale * 0.55)
                rect = pygame.Rect(0, 0, w, h)
                rect.center = (int(cur_cx), int(cur_cy))
                self._draw_card_shadow(screen, rect, alpha=int(60 * t_e))
                screen.blit(self.ctx.assets.card_back((w, h)), rect)

        # Player's own cards.
        for i in range(n):
            card_start = i * CARD_DELAY
            if age < card_start:
                break
            card_age = age - card_start
            t = min(1.0, card_age / FLIGHT_MS)
            t_e = 1 - (1 - t) ** 2

            dst_cx = x0 + i * spacing + CARD_W // 2
            dst_cy = hand_y + CARD_H // 2

            cur_cx = deck_cx + (dst_cx - deck_cx) * t_e
            cur_cy = deck_cy + (dst_cy - deck_cy) * t_e

            scale = 1.3 - 0.3 * t_e
            w, h = int(CARD_W * scale), int(CARD_H * scale)
            rect = pygame.Rect(0, 0, w, h)
            rect.center = (int(cur_cx), int(cur_cy))
            self._draw_card_shadow(screen, rect, alpha=int(90 * t_e))

            if t >= 0.85 and i < len(view.self_hand):
                # Flip reveal: last 15% of flight shows the actual card face.
                flip_t = (t - 0.85) / 0.15
                if flip_t < 0.5:
                    # Squish to 0 (back side disappearing).
                    draw_w = max(2, int(w * (1 - flip_t * 2)))
                    back = self.ctx.assets.card_back((draw_w, h))
                    br = pygame.Rect(0, 0, draw_w, h)
                    br.center = rect.center
                    screen.blit(back, br)
                else:
                    # Expand with face side.
                    draw_w = max(2, int(w * ((flip_t - 0.5) * 2)))
                    face = self.ctx.assets.card_surface(view.self_hand[i], (draw_w, h))
                    fr = pygame.Rect(0, 0, draw_w, h)
                    fr.center = rect.center
                    screen.blit(face, fr)
            else:
                back = self.ctx.assets.card_back((w, h))
                screen.blit(back, rect)

    def _draw_play_animations(self, screen: pygame.Surface) -> None:
        if not self.play_animations:
            return
        now = pygame.time.get_ticks()
        alive = []
        for anim in self.play_animations:
            age = now - anim["created"]
            duration = anim["duration"]
            if age > duration:
                continue
            t = max(0.0, min(1.0, age / duration))
            ease = 1 - (1 - t) ** 3
            sx, sy = anim["start"]
            ex, ey = anim["end"]
            cx = sx + (ex - sx) * ease
            cy = sy + (ey - sy) * ease - math.sin(t * math.pi) * 72
            scale = 1.12 - 0.12 * ease + 0.08 * math.sin(t * math.pi)
            angle = anim["angle"] * (1 - ease)
            alpha = 255
            if t > 0.82:
                alpha = int(255 * (1.0 - (t - 0.82) / 0.18))

            base = self.ctx.assets.card_surface(anim["card"], (CARD_W, CARD_H))
            card = pygame.transform.rotozoom(base, angle, scale)
            card.set_alpha(max(0, min(255, alpha)))
            rect = card.get_rect(center=(int(cx), int(cy)))
            self._draw_card_shadow(screen, rect, alpha=min(120, max(30, alpha // 2)))
            screen.blit(card, rect)

            label = self.font_b.render(f"{anim['player_name']} played", True, TEXT)
            label_bg = pygame.Surface((label.get_width() + 16, label.get_height() + 8), pygame.SRCALPHA)
            label_bg.fill((8, 10, 18, min(210, alpha)))
            label_bg.set_alpha(max(0, min(255, alpha)))
            label_rect = label_bg.get_rect(center=(rect.centerx, rect.top - 14))
            screen.blit(label_bg, label_rect)
            label.set_alpha(max(0, min(255, alpha)))
            screen.blit(label, label.get_rect(center=label_rect.center))
            alive.append(anim)
        self.play_animations = alive

    def _draw_buttons(self, screen: pygame.Surface, view) -> None:
        # ── DRAW button ─────────────────────────────────────────
        draw_r = self.draw_btn.rect
        hover_draw = draw_r.collidepoint(pygame.mouse.get_pos())
        bg_col = (90, 115, 155) if hover_draw else (50, 75, 115)
        pygame.draw.rect(screen, bg_col, draw_r, border_radius=14)
        pygame.draw.rect(screen, (200, 220, 255), draw_r, 2, border_radius=14)
        # Small card icon.
        ic = pygame.Rect(draw_r.x + 10, draw_r.centery - 18, 24, 34)
        pygame.draw.rect(screen, (245, 240, 220), ic, border_radius=5)
        pygame.draw.rect(screen, (30, 30, 60), ic, 2, border_radius=5)
        arrow = self.font_b.render("↓", True, (30, 30, 80))
        screen.blit(arrow, arrow.get_rect(center=ic.center))
        txt = self.font_b.render("DRAW", True, (245, 245, 235))
        screen.blit(txt, txt.get_rect(midleft=(draw_r.x + 44, draw_r.centery)))

        # ── END TURN button (Asian mode) ───────────────────────
        if getattr(view, "mode", "basic") == "asian":
            er = self.end_turn_btn.rect
            hover_end = er.collidepoint(pygame.mouse.get_pos())
            bg_e = (85, 95, 125) if hover_end else (45, 55, 80)
            pygame.draw.rect(screen, bg_e, er, border_radius=14)
            pygame.draw.rect(screen, (210, 220, 240), er, 2, border_radius=14)
            end_txt = self.font_b.render("END TURN", True, (245, 245, 235))
            screen.blit(end_txt, end_txt.get_rect(center=er.center))

        # ── UNO button ──────────────────────────────────────────
        uno_img = self.ctx.assets.image_first([
            "assets/buttons/UNO_button.png",
            "assets/New folder/UNO_button.png",
            "New folder/UNO_button.png",
        ], self.uno_btn.rect.size)
        if uno_img is not None:
            screen.blit(uno_img, self.uno_btn.rect)
            if self.uno_btn.rect.collidepoint(pygame.mouse.get_pos()):
                pygame.draw.rect(screen, ACCENT, self.uno_btn.rect.inflate(4, 4), 3, border_radius=22)
        else:
            # Stylised fallback.
            ur = self.uno_btn.rect
            hover_uno = ur.collidepoint(pygame.mouse.get_pos())
            bg = (220, 50, 30) if hover_uno else (185, 30, 20)
            pygame.draw.rect(screen, bg, ur, border_radius=20)
            pygame.draw.rect(screen, YELLOW, ur, 3, border_radius=20)
            uno_txt = self.font_big.render("UNO!", True, YELLOW)
            screen.blit(uno_txt, uno_txt.get_rect(center=ur.center))

        # ── LEAVE button ────────────────────────────────────────
        lr = self.leave_btn.rect
        hover_leave = lr.collidepoint(pygame.mouse.get_pos())
        bg_l = (130, 50, 50) if hover_leave else (90, 35, 35)
        pygame.draw.rect(screen, bg_l, lr, border_radius=9)
        pygame.draw.rect(screen, (220, 160, 160), lr, 2, border_radius=9)
        leave_txt = self.font.render("⏎ LEAVE", True, (245, 200, 200))
        screen.blit(leave_txt, leave_txt.get_rect(center=lr.center))

        # Blink/attention effect only when player has exactly 2 cards + has a playable card.
        try:
            hand_count = len(view.self_hand) if view.self_hand else 0
        except Exception:
            hand_count = 0
        if hand_count == 2 and self._has_playable_card(view):
            if (pygame.time.get_ticks() // 500) % 2 == 0:
                pygame.draw.rect(screen, ACCENT, self.uno_btn.rect.inflate(8, 8), 4, border_radius=24)

    def _draw_log(self, screen: pygame.Surface, view) -> None:
        if not view.log:
            return
        panel = pygame.Rect(16, 86, 280, 150)
        self._draw_glass_rect(screen, panel, fill=(7, 8, 16, 130), border=(255, 255, 255, 45), radius=14)
        y = panel.y + 12
        for line in view.log[-7:]:
            line = self._fit_text(self.font, line, panel.width - 20)
            screen.blit(self.font.render(line, True, MUTED), (panel.x + 10, y))
            y += 18

    def _play_draw_sound(self) -> None:
        self.ctx.assets.play_sound("assets/sounds/carddraw_1.mp3", "assets/sounds/carddraw_2.mp3")

    def _play_card_sound(self, card) -> None:
        if card.card_type == CardType.WILD_DRAW_FOUR:
            self.ctx.assets.play_sound("assets/sounds/cardplay_3.mp3", "assets/sounds/cardplay_2.mp3")
        elif card.card_type == CardType.DRAW_TWO:
            self.ctx.assets.play_sound("assets/sounds/cardplay_2.mp3", "assets/sounds/cardplay_1.mp3")
        else:
            self.ctx.assets.play_sound("assets/sounds/cardplay_1.mp3", "assets/sounds/cardplay_2.mp3")

    def _spawn_card_effect(self, card) -> None:
        kind = None
        duration = 760
        if card.card_type == CardType.DRAW_TWO:
            kind = "plus2"
        elif card.card_type == CardType.WILD_DRAW_FOUR:
            kind = "plus4"
            duration = 980
        elif card.card_type == CardType.REVERSE:
            kind = "reverse"
        elif card.card_type == CardType.SKIP:
            kind = "skip"
        if kind is None:
            return
        now = pygame.time.get_ticks()
        # Avoid several identical effects in the same click-frame.
        key = f"{kind}:{now // 120}"
        if key == self._last_effect_key:
            return
        self._last_effect_key = key
        # Play dedicated sound effect.
        if kind == "plus4":
            self.ctx.assets.play_sound("assets/sounds/wild_four_effect.mp3", volume=0.70)
        elif kind == "plus2":
            self.ctx.assets.play_sound("assets/sounds/carddraw_1.mp3", volume=0.65)
        self.effects.append({"kind": kind, "created": now, "duration": duration})

    def _draw_effects(self, screen: pygame.Surface) -> None:
        if not self.effects:
            return
        now = pygame.time.get_ticks()
        alive = []
        for fx in self.effects:
            age = now - fx["created"]
            if age > fx["duration"]:
                continue
            t = max(0.0, min(1.0, age / fx["duration"]))
            kind = fx["kind"]
            if kind == "plus4":
                self._draw_image_effect(screen, "assets/effects/wild_four_effects.png",
                                        t, "+4 CHAOS!", (255, 92, 235))
            elif kind == "plus2":
                self._draw_image_effect(screen, "assets/effects/plus_two_effect.png",
                                        t, "+2", (80, 190, 255))
            elif kind == "reverse":
                self._draw_reverse_effect(screen, t)
            elif kind == "skip":
                self._draw_burst_effect(screen, "NOPE!", t, (255, 220, 60))
            alive.append(fx)
        self.effects = alive

    def _effect_alpha(self, t: float) -> int:
        """Fade-in for first 20%, hold to 70%, fade-out to 100%."""
        if t < 0.20:
            return int(255 * (t / 0.20))
        elif t > 0.70:
            return int(255 * (1.0 - (t - 0.70) / 0.30))
        return 255

    def _draw_image_effect(self, screen: pygame.Surface, img_path: str,
                            t: float, label: str, color) -> None:
        """Draw an effect using the asset image with fade-in/fade-out."""
        cx, cy = SCREEN_W // 2, SCREEN_H // 2 - 30
        alpha = self._effect_alpha(t)

        img = self.ctx.assets.image_first([img_path])
        if img is not None:
            # Scale: grows in (0.55→1.0 in first 30%), gentle bob.
            if t < 0.30:
                scale = 0.55 + 0.45 * (t / 0.30)
            else:
                scale = 1.0 + 0.04 * math.sin(t * math.tau * 2)
            base_w, base_h = min(420, img.get_width()), min(260, img.get_height())
            sw, sh = int(base_w * scale), int(base_h * scale)
            scaled = pygame.transform.smoothscale(img, (sw, sh))
            scaled.set_alpha(alpha)
            screen.blit(scaled, scaled.get_rect(center=(cx, cy - 10)))
        else:
            # Fallback to procedural burst when image missing.
            self._draw_burst_effect(screen, label, t, color)
            return

        # Text label below the image.
        scale_txt = 1.0 + 0.18 * math.sin(t * math.pi)
        fsize = int(44 * scale_txt)
        font = pygame.font.SysFont("arialblack,arial", fsize, bold=True)
        shadow = font.render(label, True, (0, 0, 0))
        txt = font.render(label, True, color)
        shadow.set_alpha(alpha)
        txt.set_alpha(alpha)
        lbl_cy = cy + 110
        screen.blit(shadow, shadow.get_rect(center=(cx + 3, lbl_cy + 4)))
        screen.blit(txt, txt.get_rect(center=(cx, lbl_cy)))

    def _draw_burst_effect(self, screen: pygame.Surface, label: str, t: float, color) -> None:
        cx, cy = SCREEN_W // 2, SCREEN_H // 2 - 20
        alpha = int(255 * (1 - t))
        radius = int(36 + 120 * t)
        burst = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        for i in range(18):
            ang = (i / 18.0) * math.tau
            inner = radius * 0.25
            outer = radius * (0.85 + 0.22 * (i % 2))
            p1 = (int(cx + math.cos(ang - 0.07) * inner), int(cy + math.sin(ang - 0.07) * inner))
            p2 = (int(cx + math.cos(ang) * outer), int(cy + math.sin(ang) * outer))
            p3 = (int(cx + math.cos(ang + 0.07) * inner), int(cy + math.sin(ang + 0.07) * inner))
            pygame.draw.polygon(burst, (*color, max(0, alpha - 40)), [p1, p2, p3])
        pygame.draw.circle(burst, (*color, max(0, alpha // 3)), (cx, cy), radius, 4)
        screen.blit(burst, (0, 0))

        scale = 1.0 + 0.25 * math.sin(t * math.pi)
        font_size = int((46 if len(label) <= 3 else 38) * scale)
        font = pygame.font.SysFont("arialblack,arial", font_size, bold=True)
        txt_shadow = font.render(label, True, (0, 0, 0))
        txt = font.render(label, True, color)
        txt.set_alpha(alpha)
        txt_shadow.set_alpha(alpha)
        center = (cx, cy - int(15 * t))
        screen.blit(txt_shadow, txt_shadow.get_rect(center=(center[0] + 3, center[1] + 4)))
        screen.blit(txt, txt.get_rect(center=center))

    def _draw_reverse_effect(self, screen: pygame.Surface, t: float) -> None:
        cx, cy = SCREEN_W // 2, SCREEN_H // 2 - 14
        alpha = int(230 * (1 - t))
        radius = 76 + int(40 * t)
        fx = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        rect = pygame.Rect(0, 0, radius * 2, radius * 2)
        rect.center = (cx, cy)
        pygame.draw.arc(fx, (120, 255, 100, alpha), rect, 0.25, math.pi + 0.25, 8)
        pygame.draw.arc(fx, (120, 255, 100, alpha), rect, math.pi + 0.25, math.tau + 0.25, 8)
        for ang in (0.25, math.pi + 0.25):
            ax = int(cx + math.cos(ang) * radius)
            ay = int(cy + math.sin(ang) * radius)
            pygame.draw.polygon(
                fx,
                (120, 255, 100, alpha),
                [(ax, ay), (ax - 18, ay - 8), (ax - 8, ay + 18)],
            )
        screen.blit(fx, (0, 0))
        txt = self.font_huge.render("REVERSE!", True, (150, 255, 120))
        txt.set_alpha(alpha)
        screen.blit(txt, txt.get_rect(center=(cx, cy)))

    def _draw_chat(self, screen: pygame.Surface) -> None:
        if not self.ctx.chat_expanded:
            self._draw_chat_collapsed(screen)
        else:
            self._draw_chat_expanded(screen)

    def _draw_chat_collapsed(self, screen: pygame.Surface) -> None:
        button = pygame.Rect(SCREEN_W - 50, 76, 38, 38)
        self._draw_glass_rect(screen, button, fill=(9, 10, 24, 205), border=(145, 100, 255, 110), radius=10)
        msg_count = len(self.ctx.chat_log)
        if msg_count > 0:
            badge = pygame.Rect(button.right - 18, button.top - 8, 20, 20)
            pygame.draw.circle(screen, (255, 100, 100), badge.center, 10)
            count_text = self.font.render(str(min(msg_count, 9)), True, (255, 255, 255))
            screen.blit(count_text, count_text.get_rect(center=badge.center))
        chat_text = self.font_b.render("💬", True, ACCENT)
        screen.blit(chat_text, chat_text.get_rect(center=button.center))

    def _draw_chat_expanded(self, screen: pygame.Surface) -> None:
        panel = self.chat_panel
        self._draw_glass_rect(screen, panel, fill=(9, 10, 24, 205), border=(145, 100, 255, 110), radius=14)
        
        # Header with close button.
        header = pygame.Rect(panel.x, panel.y, panel.width, 28)
        screen.blit(self.font_b.render("Chat", True, ACCENT), (panel.x + 10, panel.y + 6))
        close_btn = pygame.Rect(panel.right - 28, panel.y + 3, 24, 24)
        pygame.draw.rect(screen, (90, 90, 90), close_btn, border_radius=4)
        close_text = self.font.render("✕", True, TEXT)
        screen.blit(close_text, close_text.get_rect(center=close_btn.center))

        max_w = panel.width - 20
        y = panel.y + 38
        for name, msg in self.ctx.chat_log[-9:]:
            line = f"{name}: {msg}"
            line = self._fit_text(self.font, line, max_w)
            screen.blit(self.font.render(line, True, TEXT), (panel.x + 10, y))
            y += 18

        input_rect = self.chat_input_rect
        pygame.draw.rect(screen, (245, 240, 225), input_rect, border_radius=6)
        border = ACCENT if self.ctx.chat_focus else (90, 90, 90)
        pygame.draw.rect(screen, border, input_rect, 2, border_radius=6)
        placeholder = "Press T to chat" if not self.ctx.chat_input else ""
        text = self.ctx.chat_input or placeholder
        color = (24, 24, 24) if self.ctx.chat_input else (110, 110, 110)
        text = self._fit_text(self.font, text, input_rect.width - 10)
        screen.blit(self.font.render(text, True, color), (input_rect.x + 6, input_rect.y + 6))

    def _fit_text(self, font: pygame.font.Font, text: str, max_w: int) -> str:
        if font.size(text)[0] <= max_w:
            return text
        trimmed = text
        while trimmed and font.size(trimmed + "...")[0] > max_w:
            trimmed = trimmed[:-1]
        return (trimmed + "...") if trimmed else "..."


    def _handle_audio_toggle(self, event: pygame.event.Event) -> bool:
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return False
        if self.sound_btn_rect.collidepoint(event.pos):
            enabled = self.ctx.assets.toggle_sound()
            if isinstance(self.ctx.toasts, list):
                self.ctx.toasts.append(("Sound on" if enabled else "Sound off", time.monotonic() + 1.4))
            if enabled:
                self.ctx.assets.play_sound("assets/sounds/cardplay_1.mp3")
            return True
        if self.music_btn_rect.collidepoint(event.pos):
            enabled = self.ctx.assets.toggle_music()
            if enabled:
                self.ctx.assets.play_music(["assets/sounds/bg_1.mp3", "assets/sounds/bg_3.mp3"], volume=0.12)
            if isinstance(self.ctx.toasts, list):
                self.ctx.toasts.append(("Music on" if enabled else "Music off", time.monotonic() + 1.4))
            return True
        return False

    def _handle_chat_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.ctx.chat_expanded:
                close_btn = pygame.Rect(self.chat_panel.right - 28, self.chat_panel.y + 3, 24, 24)
                if close_btn.collidepoint(event.pos):
                    self.ctx.chat_expanded = False
                    self.ctx.chat_focus = False
                    return True
                if self.chat_input_rect.collidepoint(event.pos):
                    self.ctx.chat_focus = True
                    return True
            else:
                if self.chat_toggle_btn.clicked(event):
                    self.ctx.chat_expanded = True
                    return True
            if self.ctx.chat_focus:
                self.ctx.chat_focus = False
        if event.type == pygame.KEYDOWN and not self.ctx.chat_focus:
            if event.key == pygame.K_t:
                if not self.ctx.chat_expanded:
                    self.ctx.chat_expanded = True
                self.ctx.chat_focus = True
                return True
        if self.ctx.chat_focus and event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.ctx.chat_focus = False
                self.ctx.chat_expanded = False
                return True
            if event.key == pygame.K_RETURN:
                msg = self.ctx.chat_input.strip()
                if msg and hasattr(self.ctx.network, "send_chat"):
                    self.ctx.network.send_chat(msg)
                    self.ctx.chat_input = ""
                return True
            if event.key == pygame.K_BACKSPACE:
                self.ctx.chat_input = self.ctx.chat_input[:-1]
                return True
            if event.unicode and event.unicode.isprintable():
                if len(self.ctx.chat_input) < 80:
                    self.ctx.chat_input += event.unicode
                return True
        return False

    # --- modals -------------------------------------------------------
    def _modal_panel(self, screen, w, h, title):
        rect = pygame.Rect((SCREEN_W - w) // 2, (SCREEN_H - h) // 2, w, h)
        pygame.draw.rect(screen, (245, 240, 225), rect, border_radius=14)
        pygame.draw.rect(screen, (24, 24, 24), rect, 3, border_radius=14)
        t = self.font_big.render(title, True, (24, 24, 24))
        screen.blit(t, t.get_rect(center=(rect.centerx, rect.top + 36)))
        return rect

    def _draw_color_picker(self, screen) -> None:
        rect = self._modal_panel(screen, 460, 220, "Pick a color")
        self.color_rects.clear()
        colors = [(Color.RED, RED), (Color.GREEN, GREEN), (Color.BLUE, BLUE), (Color.YELLOW, YELLOW)]
        sq = 70
        gap = 18
        total = sq * 4 + gap * 3
        x0 = rect.centerx - total // 2
        y = rect.bottom - sq - 30
        for (c, rgb), i in zip(colors, range(4)):
            r = pygame.Rect(x0 + i * (sq + gap), y, sq, sq)
            pygame.draw.rect(screen, rgb, r, border_radius=10)
            pygame.draw.rect(screen, (24, 24, 24), r, 2, border_radius=10)
            self.color_rects.append((c, r))

    def _draw_direction_picker(self, screen) -> None:
        rect = self._modal_panel(screen, 480, 200, "Pass hands which way?")
        bw, bh = 160, 70
        self.dir_cw_rect = pygame.Rect(rect.centerx - bw - 16, rect.bottom - bh - 24, bw, bh)
        self.dir_ccw_rect = pygame.Rect(rect.centerx + 16, rect.bottom - bh - 24, bw, bh)
        for r, label in [(self.dir_cw_rect, "↻ Clockwise (C)"),
                         (self.dir_ccw_rect, "↺ Counter (V)")]:
            pygame.draw.rect(screen, (60, 75, 97), r, border_radius=10)
            t = self.font_b.render(label, True, TEXT)
            screen.blit(t, t.get_rect(center=r.center))

    def _draw_target_picker(self, screen, view) -> None:
        others = [p for p in view.players if p.player_id != self.ctx.player_id]
        rect = self._modal_panel(screen, 460, 100 + 50 * len(others), "Swap hands with...")
        self.target_rects.clear()
        y = rect.top + 80
        for i, p in enumerate(others):
            r = pygame.Rect(rect.left + 40, y, rect.width - 80, 40)
            pygame.draw.rect(screen, (60, 75, 97), r, border_radius=8)
            t = self.font_b.render(f"{i+1}. {p.name}  ({p.card_count} cards)", True, TEXT)
            screen.blit(t, (r.left + 14, r.top + 8))
            self.target_rects.append((p.player_id, r))
            y += 50

    def _draw_reaction(self, screen, view) -> None:
        overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 140))
        screen.blit(overlay, (0, 0))
        title = self.font_big.render("⚡  REACT NOW!  ⚡", True, ACCENT)
        screen.blit(title, title.get_rect(center=(SCREEN_W // 2, SCREEN_H // 2 - 40)))
        timer = self.font_big.render(f"{view.reaction_time_left:.1f}s", True, TEXT)
        screen.blit(timer, timer.get_rect(center=(SCREEN_W // 2, SCREEN_H // 2 + 10)))
        already = self.ctx.player_id in view.reaction_responded_ids
        if already:
            done = self.font_b.render("Submitted — waiting for others", True, MUTED)
            screen.blit(done, done.get_rect(center=(SCREEN_W // 2, SCREEN_H // 2 + 60)))
        else:
            self.react_btn.draw(screen, self.font_big)

    def _draw_waiting_modal(self, screen, view) -> None:
        who = (view.awaiting_color_for_player or view.awaiting_direction_for_player
               or view.awaiting_target_for_player)
        name = next((p.name for p in view.players if p.player_id == who), who)
        rect = self._modal_panel(screen, 420, 120, f"Waiting for {name}...")
        del rect

    def _draw_bomb_decision(self, screen, view) -> None:
        overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 140))
        screen.blit(overlay, (0, 0))
        rect = self._modal_panel(screen, 520, 220, "Bomb in hand")
        info = self.font_b.render(
            f"Countdown: {view.bomb_countdown}  |  Penalty: {view.bomb_penalty}", True, (24, 24, 24)
        )
        screen.blit(info, info.get_rect(center=(rect.centerx, rect.top + 90)))
        self.hold_bomb_btn.draw(screen, self.font_b)
        self.pass_bomb_btn.draw(screen, self.font_b)
