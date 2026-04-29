from __future__ import annotations

import pygame

from src.ui.scene import AppContext, Scene
from src.ui.theme import ACCENT, BG, BG_DARK, MUTED, SCREEN_H, SCREEN_W, TEXT
from src.ui.widgets import Button


class EndGameScene(Scene):
    def __init__(self, ctx: AppContext, back_menu_cb) -> None:
        super().__init__(ctx)
        self.back_menu_cb = back_menu_cb
        self.font_big = pygame.font.SysFont("arialblack,arial", 48, bold=True)
        self.font = pygame.font.SysFont("arial", 22, bold=True)
        self.small = pygame.font.SysFont("arial", 18)
        cx = SCREEN_W // 2
        self.btn = Button(pygame.Rect(cx - 130, SCREEN_H - 110, 260, 56), "BACK TO MENU")

    def handle_event(self, event: pygame.event.Event) -> None:
        if self.btn.clicked(event):
            self.back_menu_cb()

    def draw(self, screen: pygame.Surface) -> None:
        screen.fill(BG)
        pygame.draw.ellipse(screen, BG_DARK, (60, 80, SCREEN_W - 120, SCREEN_H - 220))
        view = self.ctx.current_view
        cx = SCREEN_W // 2
        title = self.font_big.render("🏆  WINNER  🏆", True, ACCENT)
        screen.blit(title, title.get_rect(center=(cx, 180)))
        if view is not None:
            winner = next((p for p in view.players if p.player_id == view.winner_id), None)
            name = winner.name if winner else (view.winner_id or "—")
            wn = self.font_big.render(name, True, TEXT)
            screen.blit(wn, wn.get_rect(center=(cx, 260)))
            screen.blit(self.font.render("Final hands:", True, TEXT),
                        (cx - 140, 340))
            for i, p in enumerate(view.players):
                if p.player_id == view.winner_id:
                    continue
                t = self.small.render(f"{p.name}: {p.card_count} cards", True, MUTED)
                screen.blit(t, (cx - 120, 380 + i * 28))
        self.btn.draw(screen, self.font)
