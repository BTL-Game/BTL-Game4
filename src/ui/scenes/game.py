from __future__ import annotations

import pygame

from src.core.actions import (
    ChooseColor,
    ChooseDirection,
    ChooseTarget,
    DrawCard,
    PlayCard,
    Reaction,
    DeclareUno,
)
from src.core.cards import Color, CardType
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


class GameScene(Scene):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__(ctx)
        self.font = pygame.font.SysFont("arial", 16)
        self.font_b = pygame.font.SysFont("arial", 18, bold=True)
        self.font_big = pygame.font.SysFont("arial", 28, bold=True)
        self.draw_btn = Button(pygame.Rect(SCREEN_W - 200, SCREEN_H - 60, 80, 44), "DRAW")
        self.uno_btn = Button(pygame.Rect(SCREEN_W - 110, SCREEN_H - 60, 90, 44), "UNO!")
        self.react_btn = Button(pygame.Rect(SCREEN_W // 2 - 70, SCREEN_H // 2 + 110, 140, 50), "REACT!")
        self.card_rects: list[tuple[int, pygame.Rect]] = []
        self.color_rects: list[tuple[Color, pygame.Rect]] = []
        self.target_rects: list[tuple[str, pygame.Rect]] = []
        self.dir_cw_rect = pygame.Rect(0, 0, 0, 0)
        self.dir_ccw_rect = pygame.Rect(0, 0, 0, 0)
        self.draw_pile_rect = pygame.Rect(0, 0, 0, 0)
        # Chat UI
        self.chat_panel = pygame.Rect(SCREEN_W - 320, 76, 300, 260)
        self.chat_toggle_btn = Button(pygame.Rect(SCREEN_W - 50, 76, 38, 38), "💬")
        self.chat_input_rect = pygame.Rect(
            self.chat_panel.x + 12,
            self.chat_panel.bottom - 40,
            self.chat_panel.width - 24,
            30,
        )

        # Local UNO declaration state (client-side indicator)
        self.uno_declared: bool = False
        self.uno_declared_until: int = 0

    def _has_playable_card(self, view) -> bool:
        """Check if the player has at least one playable card in their hand."""
        try:
            if view is None or view.self_hand is None or view.top_card is None:
                return False
            for card in view.self_hand:
                # WILD and WILD_DRAW_FOUR are always playable
                if card.card_type in (CardType.WILD, CardType.WILD_DRAW_FOUR):
                    return True
                # Match by color
                if card.color == view.current_color:
                    return True
                # Match NUMBER by value
                if card.card_type == CardType.NUMBER and view.top_card.card_type == CardType.NUMBER and card.value == view.top_card.value:
                    return True
                # Match by card type (SKIP, DRAW_TWO, REVERSE, etc.)
                if card.card_type == view.top_card.card_type and card.card_type != CardType.NUMBER:
                    return True
            return False
        except Exception:
            return False

    # ------------------------------------------------------------------
    # input
    # ------------------------------------------------------------------
    def handle_event(self, event: pygame.event.Event) -> None:
        view = self.ctx.current_view
        if view is None:
            return

        # Reaction event takes priority over everything else.
        if view.reaction_active:
            if self.react_btn.clicked(event):
                self.ctx.network.send(self.ctx.player_id, Reaction())
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
            self.ctx.network.send(self.ctx.player_id, DrawCard())
            return
        # UNO declaration button
        if self.uno_btn.clicked(event):
            # Only allow declaring UNO when player has exactly 2 cards
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
                    else:
                        print("[WARN] network interface not available for DeclareUno")
                except Exception as e:
                    import traceback

                    print("[ERROR] Exception while sending DeclareUno:")
                    traceback.print_exc()
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.draw_pile_rect.collidepoint(event.pos):
                self.ctx.network.send(self.ctx.player_id, DrawCard())
                return
            for idx, rect in self.card_rects:
                if rect.collidepoint(event.pos):
                    self.ctx.network.send(self.ctx.player_id, PlayCard(hand_index=idx))
                    return

    # ------------------------------------------------------------------
    # rendering
    # ------------------------------------------------------------------
    def draw(self, screen: pygame.Surface) -> None:
        view = self.ctx.current_view
        screen.fill(BG)
        if view is None:
            return

        self._draw_table_oval(screen)
        self._draw_top_bar(screen, view)
        self._draw_opponents(screen, view)
        self._draw_center_piles(screen, view)
        self._draw_log(screen, view)
        self._draw_chat(screen)
        self._draw_hand(screen, view)
        self._draw_buttons(screen, view)

        # Modals on top.
        if view.reaction_active:
            self._draw_reaction(screen, view)
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

    def _draw_table_oval(self, screen: pygame.Surface) -> None:
        pygame.draw.ellipse(screen, BG_DARK, (60, 100, SCREEN_W - 120, SCREEN_H - 260))

    def _draw_top_bar(self, screen: pygame.Surface, view) -> None:
        pygame.draw.rect(screen, (0, 0, 0, 80), (0, 0, SCREEN_W, 56))
        turn_name = next(
            (p.name for p in view.players if p.player_id == view.turn_player_id),
            "?",
        )
        you_turn = view.turn_player_id == self.ctx.player_id
        dir_str = "↻ CW" if view.direction == 1 else "↺ CCW"
        col = view.current_color.value.upper() if view.current_color else "—"
        col_rgb = COLOR_RGB.get(view.current_color, MUTED)

        screen.blit(self.font_b.render(f"Room {view.room_code}", True, TEXT), (16, 14))
        turn_text = f"Turn: {'YOU' if you_turn else turn_name}"
        screen.blit(self.font_b.render(turn_text, True, ACCENT if you_turn else TEXT), (180, 14))
        # Show local UNO indicator near turn text when declared recently
        if self.uno_declared and pygame.time.get_ticks() < self.uno_declared_until:
            txt_w = self.font_b.size(turn_text)[0]
            tag = self.font_b.render("UNO!", True, (255, 200, 50))
            screen.blit(tag, (180 + txt_w + 8, 14))
        screen.blit(self.font_b.render(f"Dir: {dir_str}", True, TEXT), (380, 14))
        screen.blit(self.font_b.render("Color:", True, TEXT), (520, 14))
        pygame.draw.circle(screen, col_rgb, (610, 24), 12)
        screen.blit(self.font.render(col, True, TEXT), (628, 16))
        screen.blit(
            self.font_b.render(f"Pending: +{view.pending_penalty}", True,
                               (255, 120, 120) if view.pending_penalty else TEXT),
            (760, 14),
        )
        screen.blit(self.font.render(f"Deck: {view.draw_count}", True, MUTED), (940, 18))

    def _draw_opponents(self, screen: pygame.Surface, view) -> None:
        others = [p for p in view.players if p.player_id != self.ctx.player_id]
        # Top, left, right slots based on count.
        slots = []
        if len(others) == 1:
            slots = [("top", SCREEN_W // 2, 130)]
        elif len(others) == 2:
            slots = [("left", 130, SCREEN_H // 2 - 30), ("right", SCREEN_W - 130, SCREEN_H // 2 - 30)]
        elif len(others) >= 3:
            slots = [
                ("left", 130, SCREEN_H // 2 - 30),
                ("top", SCREEN_W // 2, 130),
                ("right", SCREEN_W - 130, SCREEN_H // 2 - 30),
            ]
        for (where, cx, cy), opp in zip(slots, others):
            self._draw_opponent(screen, opp, cx, cy, where, opp.player_id == view.turn_player_id)

    def _draw_opponent(self, screen, opp, cx, cy, where, is_turn) -> None:
        # Mini back-of-card row.
        n = max(1, min(opp.card_count, 7))
        mini = (40, 60)
        spacing = 14
        total_w = mini[0] + spacing * (n - 1)
        x0 = cx - total_w // 2
        y = cy
        for i in range(n):
            back = self.ctx.assets.card_back(mini)
            if not opp.connected:
                back = back.copy()
                back.set_alpha(110)
            screen.blit(back, (x0 + i * spacing, y))
        name_color = ACCENT if is_turn else TEXT
        if not opp.connected:
            name_color = (170, 170, 170)
        name = self.font_b.render(f"{opp.name} ({opp.card_count})", True, name_color)
        screen.blit(name, name.get_rect(center=(cx, y - 16)))
        if is_turn and opp.connected:
            pygame.draw.rect(screen, ACCENT,
                             (x0 - 6, y - 28, total_w + mini[0] + 12, mini[1] + 36),
                             2, border_radius=8)
        if not opp.connected:
            remain_total = max(0, int(60 - opp.disconnect_seconds))
            remain_skip = max(0, int(30 - opp.disconnect_seconds))
            label = (
                f"DISCONNECTED  skip in {remain_skip}s"
                if remain_skip > 0
                else f"DISCONNECTED  remove in {remain_total}s"
            )
            tag = self.font.render(label, True, (255, 160, 120))
            screen.blit(tag, tag.get_rect(center=(cx, y + mini[1] + 14)))

    def _draw_center_piles(self, screen: pygame.Surface, view) -> None:
        cx, cy = SCREEN_W // 2, SCREEN_H // 2 - 10
        # Draw pile (left).
        self.draw_pile_rect = pygame.Rect(cx - CARD_W - 30, cy - CARD_H // 2, CARD_W, CARD_H)
        if view.draw_count > 0:
            screen.blit(self.ctx.assets.card_back((CARD_W, CARD_H)), self.draw_pile_rect)
        else:
            pygame.draw.rect(screen, BG_DARK, self.draw_pile_rect, border_radius=12)
        screen.blit(self.font.render(f"DRAW", True, MUTED),
                    (self.draw_pile_rect.centerx - 18, self.draw_pile_rect.bottom + 4))

        # Discard pile (right).
        disc = pygame.Rect(cx + 30, cy - CARD_H // 2, CARD_W, CARD_H)
        if view.top_card is not None:
            surf = self.ctx.assets.card_surface(view.top_card, (CARD_W, CARD_H))
            screen.blit(surf, disc)
        else:
            pygame.draw.rect(screen, BG_DARK, disc, border_radius=12)
        screen.blit(self.font.render("DISCARD", True, MUTED),
                    (disc.centerx - 28, disc.bottom + 4))

    def _draw_hand(self, screen: pygame.Surface, view) -> None:
        self.card_rects.clear()
        n = len(view.self_hand)
        if n == 0:
            return
        max_w = SCREEN_W - 240
        spacing = min(CARD_W + 8, max_w // max(1, n))
        total_w = spacing * (n - 1) + CARD_W
        x0 = (SCREEN_W - total_w) // 2
        y = SCREEN_H - CARD_H - 30
        mouse = pygame.mouse.get_pos()
        is_my_turn = view.turn_player_id == self.ctx.player_id
        for idx, card in enumerate(view.self_hand):
            rect = pygame.Rect(x0 + idx * spacing, y, CARD_W, CARD_H)
            hover = rect.collidepoint(mouse)
            if hover:
                rect = rect.move(0, -16)
            surf = self.ctx.assets.card_surface(card, (CARD_W, CARD_H))
            screen.blit(surf, rect)
            if is_my_turn and hover:
                pygame.draw.rect(screen, ACCENT, rect, 3, border_radius=12)
            self.card_rects.append((idx, rect))

    def _draw_buttons(self, screen: pygame.Surface, view) -> None:
        self.draw_btn.draw(screen, self.font_b)
        self.uno_btn.draw(screen, self.font_b)
        # Blink/attention effect only when player has exactly 2 cards + has a playable card
        try:
            hand_count = len(view.self_hand) if view.self_hand else 0
        except Exception:
            hand_count = 0
        if hand_count == 2 and self._has_playable_card(view):
            if (pygame.time.get_ticks() // 500) % 2 == 0:
                pygame.draw.rect(screen, ACCENT, self.uno_btn.rect, 3, border_radius=10)

    def _draw_log(self, screen: pygame.Surface, view) -> None:
        x = 16
        y = 70
        for line in view.log[-7:]:
            screen.blit(self.font.render(line, True, MUTED), (x, y))
            y += 18

    def _draw_chat(self, screen: pygame.Surface) -> None:
        if not self.ctx.chat_expanded:
            self._draw_chat_collapsed(screen)
        else:
            self._draw_chat_expanded(screen)

    def _draw_chat_collapsed(self, screen: pygame.Surface) -> None:
        button = pygame.Rect(SCREEN_W - 50, 76, 38, 38)
        pygame.draw.rect(screen, PANEL, button, border_radius=8)
        pygame.draw.rect(screen, (60, 70, 80), button, 1, border_radius=8)
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
        pygame.draw.rect(screen, PANEL, panel, border_radius=10)
        pygame.draw.rect(screen, (60, 70, 80), panel, 1, border_radius=10)
        
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
