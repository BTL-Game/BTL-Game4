from __future__ import annotations

import pygame

from src.core.actions import KickPlayer, StartMatch
from src.ui.scene import AppContext, Scene
from src.ui.theme import ACCENT, BG, BG_DARK, MUTED, PANEL, SCREEN_H, SCREEN_W, TEXT
from src.ui.widgets import Button


ROW_Y0 = 180
ROW_DY = 50
LIST_LEFT = SCREEN_W // 2 - 220
LIST_RIGHT = SCREEN_W // 2 + 220


class LobbyScene(Scene):
    def __init__(self, ctx: AppContext, leave_cb) -> None:
        super().__init__(ctx)
        self.leave_cb = leave_cb
        cx = SCREEN_W // 2
        self.start_btn = Button(pygame.Rect(cx - 170, SCREEN_H - 120, 150, 50), "START")
        self.leave_btn = Button(pygame.Rect(cx + 20, SCREEN_H - 120, 150, 50), "LEAVE")
        self.font = pygame.font.SysFont("arial", 22, bold=True)
        self.small = pygame.font.SysFont("arial", 18)
        self.tiny = pygame.font.SysFont("arial", 14)
        # player_id -> Button for kick. Rebuilt each frame because list changes.
        self._kick_buttons: dict[str, Button] = {}

    def _rebuild_kick_buttons(self, view) -> None:
        self._kick_buttons.clear()
        for i, p in enumerate(view.players):
            if p.is_host:
                continue
            rect = pygame.Rect(LIST_RIGHT - 70, ROW_Y0 + i * ROW_DY - 14, 60, 28)
            self._kick_buttons[p.player_id] = Button(rect, "KICK")

    def handle_event(self, event: pygame.event.Event) -> None:
        view = self.ctx.current_view
        me = next((p for p in view.players if p.player_id == self.ctx.player_id), None) if view else None
        is_host = bool(me and me.is_host)

        if self.start_btn.clicked(event):
            ok, reason = self.ctx.network.send(self.ctx.player_id, StartMatch())
            if not ok:
                self.ctx.error = reason or "Cannot start match."
            else:
                self.ctx.error = ""
            return
        if self.leave_btn.clicked(event):
            self.leave_cb()
            return
        if is_host:
            for target_id, btn in self._kick_buttons.items():
                if btn.clicked(event):
                    ok, reason = self.ctx.network.send(
                        self.ctx.player_id, KickPlayer(target_player_id=target_id)
                    )
                    if not ok:
                        self.ctx.error = reason or "Kick failed."
                    else:
                        self.ctx.error = ""
                    return

    def draw(self, screen: pygame.Surface) -> None:
        screen.fill(BG)
        pygame.draw.ellipse(screen, BG_DARK, (60, 80, SCREEN_W - 120, SCREEN_H - 220))
        view = self.ctx.current_view
        if view is None:
            screen.blit(self.font.render("Waiting for room state...", True, TEXT), (40, 40))
            return

        self._rebuild_kick_buttons(view)

        screen.blit(self.font.render(f"Room: {view.room_code}", True, ACCENT), (40, 30))
        me = next((p for p in view.players if p.player_id == self.ctx.player_id), None)
        is_host = bool(me and me.is_host)
        screen.blit(
            self.small.render(f"You are: {'HOST' if is_host else 'GUEST'}", True, TEXT),
            (40, 60),
        )

        title = self.font.render(f"Players ({len(view.players)}/4)", True, TEXT)
        screen.blit(title, title.get_rect(center=(SCREEN_W // 2, 130)))

        for i, p in enumerate(view.players):
            y = ROW_Y0 + i * ROW_DY
            color = ACCENT if p.is_host else TEXT
            if not p.connected:
                color = (150, 150, 150)
            dot = "●" if p.connected else "○"
            tag = "  (host)" if p.is_host else ""
            line = f"{dot}  {p.name}{tag}"
            t = self.font.render(line, True, color)
            screen.blit(t, (LIST_LEFT, y - t.get_height() // 2))
            if not p.connected:
                remain = max(0, int(60 - p.disconnect_seconds))
                badge = self.tiny.render(
                    f"disconnected — {remain}s before remove", True, (255, 160, 120)
                )
                screen.blit(badge, (LIST_LEFT + 200, y - badge.get_height() // 2))
            if p.player_id == self.ctx.player_id:
                you = self.tiny.render("(you)", True, MUTED)
                screen.blit(you, (LIST_LEFT - 50, y - you.get_height() // 2))

        for i in range(len(view.players), 4):
            y = ROW_Y0 + i * ROW_DY
            t = self.small.render("○  ...waiting...", True, MUTED)
            screen.blit(t, (LIST_LEFT, y - t.get_height() // 2))

        if is_host:
            for btn in self._kick_buttons.values():
                btn.draw(screen, self.tiny)

        # Event log panel (right side).
        log_rect = pygame.Rect(SCREEN_W - 320, 100, 280, SCREEN_H - 260)
        pygame.draw.rect(screen, PANEL, log_rect, border_radius=8)
        pygame.draw.rect(screen, (60, 70, 80), log_rect, 1, border_radius=8)
        screen.blit(self.small.render("Activity", True, ACCENT), (log_rect.x + 10, log_rect.y + 8))
        for i, msg in enumerate(view.log[-12:]):
            t = self.tiny.render(msg, True, TEXT)
            screen.blit(t, (log_rect.x + 10, log_rect.y + 36 + i * 18))

        self.start_btn.draw(screen, self.font)
        self.leave_btn.draw(screen, self.font)
        if not is_host:
            info = self.small.render("Only host can start the match.", True, ACCENT)
            screen.blit(info, info.get_rect(center=(SCREEN_W // 2, SCREEN_H - 160)))
        hint = self.tiny.render(
            "Demo disconnect: close this terminal. Reconnect: re-run the client.",
            True, MUTED,
        )
        screen.blit(hint, (40, SCREEN_H - 30))
        if self.ctx.error:
            err = self.small.render(self.ctx.error, True, (255, 120, 120))
            screen.blit(err, err.get_rect(center=(SCREEN_W // 2, 90)))
