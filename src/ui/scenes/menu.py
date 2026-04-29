from __future__ import annotations

import pygame

from src.ui.scene import AppContext, Scene
from src.ui.theme import (
    ACCENT,
    BG,
    BG_DARK,
    RED,
    SCREEN_H,
    SCREEN_W,
    TEXT,
    YELLOW,
)
from src.ui.widgets import Button


class MenuScene(Scene):
    def __init__(self, ctx: AppContext, go_lobby_cb) -> None:
        super().__init__(ctx)
        self.go_lobby_cb = go_lobby_cb
        bw, bh = 260, 56
        cx = SCREEN_W // 2
        self.create_btn = Button(pygame.Rect(cx - bw // 2, 380, bw, bh), "CREATE ROOM")
        self.join_btn = Button(pygame.Rect(cx - bw // 2, 450, bw, bh), "JOIN ROOM")
        self.title_font = pygame.font.SysFont("arialblack,arial", 64, bold=True, italic=True)
        self.font = pygame.font.SysFont("arial", 22, bold=True)
        self.small = pygame.font.SysFont("arial", 18)

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN and event.key == pygame.K_BACKSPACE:
            self.ctx.player_name = self.ctx.player_name[:-1]
        elif event.type == pygame.KEYDOWN and event.unicode.isprintable():
            self.ctx.player_name = (self.ctx.player_name + event.unicode)[:20]
        if self.create_btn.clicked(event):
            self.go_lobby_cb(create=True)
        if self.join_btn.clicked(event):
            self.go_lobby_cb(create=False)

    def draw(self, screen: pygame.Surface) -> None:
        screen.fill(BG)
        pygame.draw.ellipse(screen, BG_DARK, (60, 80, SCREEN_W - 120, SCREEN_H - 160))

        # UNO logo: red oval + UNO letters.
        cx = SCREEN_W // 2
        oval = pygame.Rect(cx - 240, 140, 480, 160)
        pygame.draw.ellipse(screen, RED, oval)
        title = self.title_font.render("UNO", True, YELLOW)
        screen.blit(title, title.get_rect(center=oval.center))

        sub = self.font.render("Custom UNO Online", True, TEXT)
        screen.blit(sub, sub.get_rect(center=(cx, 320)))

        prompt = self.small.render(f"Name: {self.ctx.player_name or 'Player'} (type to edit)",
                                    True, ACCENT)
        screen.blit(prompt, prompt.get_rect(center=(cx, 350)))

        self.create_btn.draw(screen, self.font)
        self.join_btn.draw(screen, self.font)
        if self.ctx.error:
            err = self.small.render(self.ctx.error, True, (255, 110, 110))
            screen.blit(err, err.get_rect(center=(cx, 540)))
