from __future__ import annotations

import pygame

from src.core.actions import StartMatch
from src.ui.scene import AppContext, Scene
from src.ui.theme import ACCENT, BG, BG_DARK, MUTED, SCREEN_H, SCREEN_W, TEXT
from src.ui.widgets import Button


class LobbyScene(Scene):
    def __init__(self, ctx: AppContext, leave_cb) -> None:
        super().__init__(ctx)
        self.leave_cb = leave_cb
        cx = SCREEN_W // 2
        self.start_btn = Button(pygame.Rect(cx - 170, SCREEN_H - 120, 150, 50), "START")
        self.leave_btn = Button(pygame.Rect(cx + 20, SCREEN_H - 120, 150, 50), "LEAVE")
        self.font = pygame.font.SysFont("arial", 22, bold=True)
        self.small = pygame.font.SysFont("arial", 18)

    def handle_event(self, event: pygame.event.Event) -> None:
        if self.start_btn.clicked(event):
            ok, reason = self.ctx.network.send(self.ctx.player_id, StartMatch())
            if not ok:
                self.ctx.error = reason or "Cannot start match."
            else:
                self.ctx.error = ""
        if self.leave_btn.clicked(event):
            self.leave_cb()

    def draw(self, screen: pygame.Surface) -> None:
        screen.fill(BG)
        pygame.draw.ellipse(screen, BG_DARK, (60, 80, SCREEN_W - 120, SCREEN_H - 220))
        view = self.ctx.current_view
        if view is None:
            screen.blit(self.font.render("Waiting for room state...", True, TEXT), (40, 40))
            return
        screen.blit(self.font.render(f"Room: {view.room_code}", True, ACCENT), (40, 30))
        me = next((p for p in view.players if p.player_id == self.ctx.player_id), None)
        is_host = bool(me and me.is_host)
        screen.blit(self.small.render(f"You are: {'HOST' if is_host else 'GUEST'}",
                                      True, TEXT), (40, 60))

        title = self.font.render(f"Players ({len(view.players)}/4)", True, TEXT)
        screen.blit(title, title.get_rect(center=(SCREEN_W // 2, 130)))
        for i, p in enumerate(view.players):
            line = f"●  {p.name}{'  (host)' if p.is_host else ''}"
            t = self.font.render(line, True, ACCENT if p.is_host else TEXT)
            screen.blit(t, (SCREEN_W // 2 - 160, 180 + i * 44))
        for i in range(len(view.players), 4):
            t = self.small.render("○  ...waiting...", True, MUTED)
            screen.blit(t, (SCREEN_W // 2 - 160, 180 + i * 44))

        self.start_btn.draw(screen, self.font)
        self.leave_btn.draw(screen, self.font)
        if not is_host:
            info = self.small.render("Only host can start the match.", True, ACCENT)
            screen.blit(info, info.get_rect(center=(SCREEN_W // 2, SCREEN_H - 160)))
        if self.ctx.error:
            err = self.small.render(self.ctx.error, True, (255, 120, 120))
            screen.blit(err, err.get_rect(center=(SCREEN_W // 2, 90)))
