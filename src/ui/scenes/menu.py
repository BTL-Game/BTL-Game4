from __future__ import annotations

import pygame

from src.ui.scene import AppContext, Scene
from src.ui.theme import (
    ACCENT,
    BG,
    BG_DARK,
    MUTED,
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
        bw, bh = 260, 56
        cx = SCREEN_W // 2
        self.continue_btn = Button(pygame.Rect(cx - bw // 2, 460, bw, bh), "CONTINUE")
        self.title_font = pygame.font.SysFont("arialblack,arial", 64, bold=True, italic=True)
        self.font = pygame.font.SysFont("arial", 22, bold=True)
        self.small = pygame.font.SysFont("arial", 18)
        self.tiny = pygame.font.SysFont("arial", 14)
        self.name_box = pygame.Rect(cx - 160, 400, 320, 44)

    def handle_event(self, event: pygame.event.Event) -> None:
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
        pygame.draw.ellipse(screen, BG_DARK, (60, 80, SCREEN_W - 120, SCREEN_H - 160))

        cx = SCREEN_W // 2
        oval = pygame.Rect(cx - 240, 140, 480, 160)
        pygame.draw.ellipse(screen, RED, oval)
        title = self.title_font.render("UNO", True, YELLOW)
        screen.blit(title, title.get_rect(center=oval.center))

        sub = self.font.render("Custom UNO Online", True, TEXT)
        screen.blit(sub, sub.get_rect(center=(cx, 320)))

        prompt = self.small.render("Enter your name:", True, ACCENT)
        screen.blit(prompt, prompt.get_rect(center=(cx, 370)))

        pygame.draw.rect(screen, (245, 240, 225), self.name_box, border_radius=8)
        pygame.draw.rect(screen, ACCENT, self.name_box, 2, border_radius=8)
        nm = self.font.render(self.ctx.player_name or " ", True, (24, 24, 24))
        screen.blit(nm, nm.get_rect(center=self.name_box.center))

        self.continue_btn.draw(screen, self.font)

        server_info = self.tiny.render(
            f"Server: {self.ctx.server_address or 'local'}",
            True,
            MUTED,
        )
        screen.blit(server_info, server_info.get_rect(center=(cx, SCREEN_H - 60)))

        if self.ctx.error:
            err = self.small.render(self.ctx.error, True, (255, 110, 110))
            screen.blit(err, err.get_rect(center=(cx, 540)))
