from __future__ import annotations

import pygame

from src.core.actions import (
    ChooseColor,
    ChooseDirection,
    ChooseTarget,
    DrawCard,
    PlayCard,
    Reaction,
)
from src.core.cards import Color
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

        # Normal play.
        if self.draw_btn.clicked(event):
            self.ctx.network.send(self.ctx.player_id, DrawCard())
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
            screen.blit(back, (x0 + i * spacing, y))
        name_color = ACCENT if is_turn else TEXT
        name = self.font_b.render(f"{opp.name} ({opp.card_count})", True, name_color)
        screen.blit(name, name.get_rect(center=(cx, y - 16)))
        if is_turn:
            pygame.draw.rect(screen, ACCENT,
                             (x0 - 6, y - 28, total_w + mini[0] + 12, mini[1] + 36),
                             2, border_radius=8)

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

    def _draw_log(self, screen: pygame.Surface, view) -> None:
        x = 16
        y = 70
        for line in view.log[-7:]:
            screen.blit(self.font.render(line, True, MUTED), (x, y))
            y += 18

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
