from __future__ import annotations

import pygame

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
    def __init__(self, ctx: AppContext, on_continue) -> None:
        super().__init__(ctx)
        self._on_continue = on_continue
        self.continue_btn = Button(pygame.Rect(0, 0, 260, 54), "PLAY")
        self.title_font = pygame.font.SysFont("impact,arialblack", 86)
        self.font = pygame.font.SysFont("trebuchetms,arial", 22, bold=True)
        self.small = pygame.font.SysFont("trebuchetms,arial", 18)
        self.tiny = pygame.font.SysFont("trebuchetms,arial", 14)
        self.name_box = pygame.Rect(0, 0, 320, 46)

    def _layout(self) -> pygame.Rect:
        panel = pygame.Rect(SCREEN_W - 420, 210, 340, 300)
        self.name_box = pygame.Rect(panel.x + 26, panel.y + 104, panel.width - 52, 46)
        self.continue_btn.rect = pygame.Rect(panel.x + 26, panel.y + 178, panel.width - 52, 54)
        return panel

    def handle_event(self, event: pygame.event.Event) -> None:
        self._layout()
        if event.type == pygame.KEYDOWN and event.key == pygame.K_BACKSPACE:
            self.ctx.player_name = self.ctx.player_name[:-1]
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN:
            if self.ctx.player_name.strip():
                self._on_continue()
        elif event.type == pygame.KEYDOWN and event.unicode.isprintable():
            self.ctx.player_name = (self.ctx.player_name + event.unicode)[:20]
        if self.continue_btn.clicked(event):
            if self.ctx.player_name.strip():
                self._on_continue()
            else:
                self.ctx.error = "Enter a name first."

    def draw(self, screen: pygame.Surface) -> None:
        screen.fill(BG)
        pygame.draw.ellipse(screen, BG_DARK, (-80, 140, SCREEN_W - 40, SCREEN_H - 200))
        pygame.draw.polygon(screen, (22, 118, 70), [(0, 120), (SCREEN_W, 40), (SCREEN_W, 160), (0, 240)])

        # Hero card on the left.
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

        # Right-side panel for input.
        panel = self._layout()
        pygame.draw.rect(screen, PANEL_LIGHT, panel, border_radius=16)
        pygame.draw.rect(screen, (35, 45, 55), panel, 2, border_radius=16)
        screen.blit(self.font.render("Join the table", True, (24, 24, 24)), (panel.x + 26, panel.y + 26))
        hint = self.small.render("Enter your name", True, (70, 70, 70))
        screen.blit(hint, (panel.x + 26, panel.y + 70))

        pygame.draw.rect(screen, (245, 240, 225), self.name_box, border_radius=8)
        pygame.draw.rect(screen, ACCENT, self.name_box, 2, border_radius=8)
        nm = self.font.render(self.ctx.player_name or " ", True, (24, 24, 24))
        screen.blit(nm, nm.get_rect(center=self.name_box.center))

        self.continue_btn.draw(screen, self.font)

        tip = self.tiny.render("Press Enter to continue", True, (70, 70, 70))
        screen.blit(tip, (panel.x + 26, panel.y + 244))

        server_info = self.tiny.render(
            f"Server: {self.ctx.server_address or 'local'}",
            True,
            MUTED,
        )
        screen.blit(server_info, (panel.x + 26, panel.bottom + 18))

        if self.ctx.error:
            err = self.small.render(self.ctx.error, True, (255, 110, 110))
            screen.blit(err, err.get_rect(center=(panel.centerx, panel.bottom + 52)))
