from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pygame


@dataclass
class AppContext:
    network: Any
    assets: Any
    player_id: str = ""
    player_name: str = ""
    room_code: str = ""
    error: str = ""
    current_view: Any = None
    views_by_player: Any = None
    seated_player_ids: Any = None
    server_address: str = ""
    # toasts: list of (text, expires_at_monotonic)
    toasts: Any = None
    chat_log: list[tuple[str, str]] = field(default_factory=list)
    chat_input: str = ""
    chat_focus: bool = False
    chat_expanded: bool = True


class Scene:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    def handle_event(self, event: pygame.event.Event) -> None:
        pass

    def update(self, dt: float) -> None:
        del dt

    def draw(self, screen: pygame.Surface) -> None:
        del screen
