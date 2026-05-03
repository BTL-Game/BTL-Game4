from __future__ import annotations

import pygame

from src.network.server_probe import ServerEntry, ServerProbe, ServerStatus
from src.ui.scene import AppContext, Scene
from src.ui.theme import (
    ACCENT,
    BG,
    BG_DARK,
    MUTED,
    PANEL_LIGHT,
    RED,
    SCREEN_H,
    SCREEN_W,
    TEXT,
    YELLOW,
)
from src.ui.widgets import Button


class MenuScene(Scene):
    def __init__(
        self,
        ctx: AppContext,
        on_continue,
        servers: list[ServerEntry] | None = None,
        probe: ServerProbe | None = None,
        selected_id: str | None = None,
    ) -> None:
        super().__init__(ctx)
        self._on_continue = on_continue
        self._servers = list(servers or [])
        self._probe = probe
        self._selected_id = selected_id or (self._servers[0].id if self._servers else "")
        self._dropdown_open = False

        self.continue_btn = Button(pygame.Rect(0, 0, 260, 54), "PLAY")
        self.title_font = pygame.font.SysFont("impact,arialblack", 86)
        self.font = pygame.font.SysFont("trebuchetms,arial", 22, bold=True)
        self.small = pygame.font.SysFont("trebuchetms,arial", 18)
        self.tiny = pygame.font.SysFont("trebuchetms,arial", 14)
        self.name_box = pygame.Rect(0, 0, 320, 46)
        self.dropdown_rect = pygame.Rect(0, 0, 320, 38)

    # ------------------------------------------------------------------
    # selection helpers
    # ------------------------------------------------------------------
    @property
    def selected(self) -> ServerEntry | None:
        for s in self._servers:
            if s.id == self._selected_id:
                return s
        return self._servers[0] if self._servers else None

    def _statuses(self) -> dict[str, ServerStatus]:
        return self._probe.snapshot() if self._probe else {}

    def _status_glyph(self, st: ServerStatus | None) -> tuple[str, tuple[int, int, int]]:
        if st is None or not st.last_checked:
            return ("…", (180, 180, 180))
        if not st.online:
            return ("●", (200, 60, 60))
        if st.max_connections and st.n_connections >= 0.85 * st.max_connections:
            return ("●", (220, 160, 40))  # busy
        return ("●", (60, 200, 110))

    def _status_summary(self, st: ServerStatus | None) -> str:
        if st is None or not st.last_checked:
            return "checking…"
        if not st.online:
            return "offline"
        parts = [f"{st.n_players} players", f"{st.n_visible_rooms} rooms"]
        if st.latency_ms is not None:
            parts.append(f"{st.latency_ms}ms")
        return ", ".join(parts)

    # ------------------------------------------------------------------
    # layout
    # ------------------------------------------------------------------
    def _layout(self) -> pygame.Rect:
        panel = pygame.Rect(SCREEN_W - 420, 170, 340, 380)
        self.dropdown_rect = pygame.Rect(panel.x + 26, panel.y + 70, panel.width - 52, 38)
        self.name_box = pygame.Rect(panel.x + 26, panel.y + 168, panel.width - 52, 46)
        self.continue_btn.rect = pygame.Rect(panel.x + 26, panel.y + 242, panel.width - 52, 54)
        return panel

    def _option_rects(self) -> list[tuple[ServerEntry, pygame.Rect]]:
        rects: list[tuple[ServerEntry, pygame.Rect]] = []
        if not self._dropdown_open:
            return rects
        x, y = self.dropdown_rect.x, self.dropdown_rect.bottom + 4
        w = self.dropdown_rect.width
        h = 42
        for i, s in enumerate(self._servers):
            rects.append((s, pygame.Rect(x, y + i * (h + 2), w, h)))
        return rects

    # ------------------------------------------------------------------
    # input
    # ------------------------------------------------------------------
    def handle_event(self, event: pygame.event.Event) -> None:
        self._layout()

        # Dropdown interaction takes priority while open.
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.dropdown_rect.collidepoint(event.pos):
                self._dropdown_open = not self._dropdown_open
                return
            if self._dropdown_open:
                for entry, rect in self._option_rects():
                    if rect.collidepoint(event.pos):
                        self._selected_id = entry.id
                        self._dropdown_open = False
                        self.ctx.error = ""
                        return
                # Click outside the dropdown closes it without selecting.
                self._dropdown_open = False

        # Block all other input while the menu is showing the dropdown overlay.
        if self._dropdown_open:
            return

        if event.type == pygame.KEYDOWN and event.key == pygame.K_BACKSPACE:
            self.ctx.player_name = self.ctx.player_name[:-1]
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN:
            if self.ctx.player_name.strip():
                self._submit()
        elif event.type == pygame.KEYDOWN and event.unicode.isprintable():
            self.ctx.player_name = (self.ctx.player_name + event.unicode)[:20]
        if self.continue_btn.clicked(event):
            self._submit()

    def _submit(self) -> None:
        if not self.ctx.player_name.strip():
            self.ctx.error = "Enter a name first."
            return
        entry = self.selected
        if entry is None:
            self.ctx.error = "Pick a server."
            return
        statuses = self._statuses()
        st = statuses.get(entry.id)
        if st is not None and st.last_checked and not st.online:
            self.ctx.error = f"{entry.label} is offline."
            return
        self._on_continue(entry)

    # ------------------------------------------------------------------
    # draw
    # ------------------------------------------------------------------
    def draw(self, screen: pygame.Surface) -> None:
        screen.fill(BG)
        pygame.draw.ellipse(screen, BG_DARK, (-80, 140, SCREEN_W - 40, SCREEN_H - 200))
        pygame.draw.polygon(screen, (22, 118, 70), [(0, 120), (SCREEN_W, 40), (SCREEN_W, 160), (0, 240)])

        hero = pygame.Rect(110, 140, 420, 460)
        shadow = hero.move(8, 10)
        pygame.draw.rect(screen, (8, 40, 28), shadow, border_radius=24)
        pygame.draw.rect(screen, RED, hero, border_radius=24)
        badge = pygame.Rect(hero.centerx - 150, hero.centery - 80, 300, 160)
        pygame.draw.ellipse(screen, YELLOW, badge)
        title = self.title_font.render("UNO", True, (24, 24, 24))
        screen.blit(title, title.get_rect(center=badge.center))
        sub = self.small.render("Custom UNO Online", True, TEXT)
        screen.blit(sub, sub.get_rect(center=(hero.centerx, hero.bottom - 40)))

        panel = self._layout()
        pygame.draw.rect(screen, PANEL_LIGHT, panel, border_radius=16)
        pygame.draw.rect(screen, (35, 45, 55), panel, 2, border_radius=16)
        screen.blit(self.font.render("Join the table", True, (24, 24, 24)), (panel.x + 26, panel.y + 26))

        statuses = self._statuses()

        # --- server dropdown ---
        sel = self.selected
        sel_st = statuses.get(sel.id) if sel else None
        glyph, glyph_color = self._status_glyph(sel_st)
        pygame.draw.rect(screen, (245, 240, 225), self.dropdown_rect, border_radius=8)
        pygame.draw.rect(screen, ACCENT, self.dropdown_rect, 2, border_radius=8)
        gtxt = self.small.render(glyph, True, glyph_color)
        screen.blit(gtxt, gtxt.get_rect(midleft=(self.dropdown_rect.x + 10, self.dropdown_rect.centery)))
        label = sel.label if sel else "(no server)"
        ltxt = self.small.render(label, True, (24, 24, 24))
        screen.blit(ltxt, ltxt.get_rect(midleft=(self.dropdown_rect.x + 30, self.dropdown_rect.centery)))
        chev = self.small.render("▾", True, (60, 60, 60))
        screen.blit(chev, chev.get_rect(midright=(self.dropdown_rect.right - 10, self.dropdown_rect.centery)))

        status_text = self.tiny.render(
            self._status_summary(sel_st), True, (70, 70, 70)
        )
        screen.blit(status_text, (self.dropdown_rect.x + 4, self.dropdown_rect.bottom + 6))

        # --- name box ---
        hint = self.small.render("Enter your name", True, (70, 70, 70))
        screen.blit(hint, (panel.x + 26, panel.y + 138))

        pygame.draw.rect(screen, (245, 240, 225), self.name_box, border_radius=8)
        pygame.draw.rect(screen, ACCENT, self.name_box, 2, border_radius=8)
        nm = self.font.render(self.ctx.player_name or " ", True, (24, 24, 24))
        screen.blit(nm, nm.get_rect(center=self.name_box.center))

        self.continue_btn.draw(screen, self.font)

        tip = self.tiny.render("Press Enter to continue", True, (70, 70, 70))
        screen.blit(tip, (panel.x + 26, panel.y + 308))

        if self.ctx.error:
            err = self.small.render(self.ctx.error, True, (255, 110, 110))
            screen.blit(err, err.get_rect(center=(panel.centerx, panel.bottom + 22)))

        # --- dropdown overlay (drawn last, on top of everything) ---
        if self._dropdown_open:
            for entry, rect in self._option_rects():
                st = statuses.get(entry.id)
                pygame.draw.rect(screen, (250, 246, 232), rect, border_radius=8)
                pygame.draw.rect(screen, (35, 45, 55), rect, 1, border_radius=8)
                g, gc = self._status_glyph(st)
                gt = self.small.render(g, True, gc)
                screen.blit(gt, gt.get_rect(midleft=(rect.x + 10, rect.y + 14)))
                ent = self.small.render(entry.label, True, (24, 24, 24))
                screen.blit(ent, ent.get_rect(midleft=(rect.x + 30, rect.y + 14)))
                summary = self.tiny.render(self._status_summary(st), True, MUTED)
                screen.blit(summary, summary.get_rect(midleft=(rect.x + 30, rect.y + 30)))
