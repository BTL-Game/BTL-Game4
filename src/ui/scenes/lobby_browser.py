"""Lobby browser: list available rooms, create a new room, join by code.

Polls the server's LIST_ROOMS every REFRESH_SEC seconds while visible.
"""
from __future__ import annotations

import time

import pygame

from src.ui.scene import AppContext, Scene
from src.ui.theme import (
    ACCENT,
    BG,
    BG_DARK,
    MUTED,
    PANEL,
    SCREEN_H,
    SCREEN_W,
    TEXT,
)
from src.ui.widgets import Button


REFRESH_SEC = 1.5


class LobbyBrowserScene(Scene):
    def __init__(self, ctx: AppContext, on_create, on_join, on_back) -> None:
        super().__init__(ctx)
        self._on_create = on_create
        self._on_join = on_join
        self._on_back = on_back
        self.font = pygame.font.SysFont("arial", 22, bold=True)
        self.font_b = pygame.font.SysFont("arial", 26, bold=True)
        self.small = pygame.font.SysFont("arial", 18)
        self.tiny = pygame.font.SysFont("arial", 14)

        self.code_input: str = ""
        self.code_focus: bool = False
        self._last_refresh: float = 0.0

        cx = SCREEN_W // 2
        self.create_btn = Button(pygame.Rect(cx - 320, SCREEN_H - 90, 200, 50), "CREATE ROOM")
        self.join_btn = Button(pygame.Rect(cx - 90, SCREEN_H - 90, 180, 50), "JOIN BY CODE")
        self.refresh_btn = Button(pygame.Rect(cx + 120, SCREEN_H - 90, 130, 50), "REFRESH")
        self.back_btn = Button(pygame.Rect(20, SCREEN_H - 60, 100, 40), "BACK")
        self.code_box = pygame.Rect(cx - 120, SCREEN_H - 150, 240, 40)
        self.mode_basic_btn = Button(pygame.Rect(cx - 320, SCREEN_H - 200, 150, 40), "BASIC")
        self.mode_asian_btn = Button(pygame.Rect(cx - 160, SCREEN_H - 200, 150, 40), "ASIAN")
        self.mode: str = "basic"

        self._row_rects: list[tuple[str, pygame.Rect]] = []
        # Auto-request initial list.
        self._request_list()

    def _request_list(self) -> None:
        net = self.ctx.network
        if hasattr(net, "list_rooms"):
            net.list_rooms()
        self._last_refresh = time.monotonic()

    # ------------------------------------------------------------------
    def handle_event(self, event: pygame.event.Event) -> None:
        if self.back_btn.clicked(event):
            self._on_back()
            return
        if self.create_btn.clicked(event):
            self._on_create(self.mode)
            return
        if self.mode_basic_btn.clicked(event):
            self.mode = "basic"
            return
        if self.mode_asian_btn.clicked(event):
            self.mode = "asian"
            return
        if self.refresh_btn.clicked(event):
            self._request_list()
            return
        if self.join_btn.clicked(event):
            code = self.code_input.strip()
            if len(code) == 8:
                self._on_join(code)
            else:
                self.ctx.error = "Enter an 8-digit code."
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.code_focus = self.code_box.collidepoint(event.pos)
            for code, rect in self._row_rects:
                if rect.collidepoint(event.pos):
                    self._on_join(code)
                    return
        if self.code_focus and event.type == pygame.KEYDOWN:
            if event.key == pygame.K_BACKSPACE:
                self.code_input = self.code_input[:-1]
            elif event.key == pygame.K_RETURN:
                code = self.code_input.strip()
                if len(code) == 8:
                    self._on_join(code)
                else:
                    self.ctx.error = "Enter an 8-digit code."
            elif event.unicode.isdigit() and len(self.code_input) < 8:
                self.code_input = self.code_input + event.unicode

    def update(self, dt: float) -> None:
        del dt
        if time.monotonic() - self._last_refresh >= REFRESH_SEC:
            self._request_list()

    # ------------------------------------------------------------------
    def draw(self, screen: pygame.Surface) -> None:
        screen.fill(BG)
        pygame.draw.ellipse(screen, BG_DARK, (60, 80, SCREEN_W - 120, SCREEN_H - 220))

        screen.blit(self.font_b.render("Lobby Browser", True, ACCENT), (40, 30))
        sub = self.small.render(
            f"Connected as: {self.ctx.player_name or 'Player'}",
            True,
            TEXT,
        )
        screen.blit(sub, (40, 70))

        # Room list panel.
        panel = pygame.Rect(60, 110, SCREEN_W - 120, SCREEN_H - 320)
        pygame.draw.rect(screen, PANEL, panel, border_radius=10)
        pygame.draw.rect(screen, (60, 70, 80), panel, 1, border_radius=10)

        rooms = list(getattr(self.ctx.network, "room_list", []))
        title = self.font.render(f"Available rooms ({len(rooms)})", True, ACCENT)
        screen.blit(title, (panel.x + 16, panel.y + 12))

        # Column headers.
        hy = panel.y + 50
        screen.blit(self.tiny.render("CODE", True, MUTED), (panel.x + 16, hy))
        screen.blit(self.tiny.render("HOST", True, MUTED), (panel.x + 130, hy))
        screen.blit(self.tiny.render("PLAYERS", True, MUTED), (panel.x + 320, hy))
        screen.blit(self.tiny.render("MODE", True, MUTED), (panel.x + 450, hy))
        screen.blit(self.tiny.render("STATUS", True, MUTED), (panel.x + 560, hy))

        self._row_rects.clear()
        if not rooms:
            empty = self.small.render(
                "No rooms yet. Click CREATE ROOM to start one.",
                True,
                MUTED,
            )
            screen.blit(empty, empty.get_rect(center=(panel.centerx, panel.y + 120)))
        else:
            row_y = panel.y + 78
            for r in rooms:
                row_rect = pygame.Rect(panel.x + 8, row_y - 4, panel.width - 16, 36)
                hover = row_rect.collidepoint(pygame.mouse.get_pos())
                if hover:
                    pygame.draw.rect(screen, (40, 55, 75), row_rect, border_radius=6)
                screen.blit(self.font.render(r["code"], True, ACCENT), (panel.x + 16, row_y))
                screen.blit(self.small.render(r["host_name"], True, TEXT), (panel.x + 130, row_y + 2))
                screen.blit(
                    self.small.render(f"{r['n_players']}/{r['max_players']}", True, TEXT),
                    (panel.x + 330, row_y + 2),
                )
                mode = str(r.get("mode", "basic"))
                screen.blit(self.small.render(mode, True, MUTED), (panel.x + 450, row_y + 2))
                status = "started" if r["started"] else "waiting"
                screen.blit(self.small.render(status, True, MUTED), (panel.x + 560, row_y + 2))
                self._row_rects.append((r["code"], row_rect))
                row_y += 40

        # Code input.
        screen.blit(self.small.render("Enter code:", True, TEXT), (self.code_box.x - 130, self.code_box.y + 8))
        pygame.draw.rect(screen, (245, 240, 225), self.code_box, border_radius=8)
        border = ACCENT if self.code_focus else (90, 90, 90)
        pygame.draw.rect(screen, border, self.code_box, 2, border_radius=8)
        text_surf = self.font_b.render(self.code_input or "________", True, (24, 24, 24))
        screen.blit(text_surf, text_surf.get_rect(center=self.code_box.center))

        self.create_btn.draw(screen, self.font)
        self.join_btn.draw(screen, self.font)
        self.refresh_btn.draw(screen, self.font)
        self.back_btn.draw(screen, self.small)

        # Mode selector.
        screen.blit(self.small.render("Mode:", True, TEXT), (self.mode_basic_btn.rect.x - 60, self.mode_basic_btn.rect.y + 10))
        self.mode_basic_btn.draw(screen, self.small)
        self.mode_asian_btn.draw(screen, self.small)
        if self.mode == "basic":
            pygame.draw.rect(screen, ACCENT, self.mode_basic_btn.rect.inflate(6, 6), 2, border_radius=10)
        else:
            pygame.draw.rect(screen, ACCENT, self.mode_asian_btn.rect.inflate(6, 6), 2, border_radius=10)

        if self.ctx.error:
            err = self.small.render(self.ctx.error, True, (255, 110, 110))
            screen.blit(err, err.get_rect(center=(SCREEN_W // 2, panel.bottom + 24)))

        hint = self.tiny.render("Click a row to join, or type the 8-digit code and press Enter.", True, MUTED)
        screen.blit(hint, (panel.x + 16, SCREEN_H - 165))
