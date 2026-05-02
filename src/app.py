from __future__ import annotations

import time

import pygame

from src.network.socket_client import SocketClientNetwork
from src.ui.assets import AssetManager
from src.ui.scene import AppContext
from src.ui.scene_manager import SceneManager
from src.ui.scenes.end_game import EndGameScene
from src.ui.scenes.game import GameScene
from src.ui.scenes.lobby import LobbyScene
from src.ui.scenes.lobby_browser import LobbyBrowserScene
from src.ui.scenes.menu import MenuScene
from src.ui.theme import SCREEN_H, SCREEN_W


_TOAST_FONT = None


def _draw_toasts(screen: pygame.Surface, ctx: AppContext) -> None:
    global _TOAST_FONT
    if not ctx.toasts:
        return
    if _TOAST_FONT is None:
        _TOAST_FONT = pygame.font.SysFont("arial", 16, bold=True)
    pad = 8
    margin = 12
    y = margin
    sw = screen.get_width()
    for text, _exp in ctx.toasts[-6:]:
        surf = _TOAST_FONT.render(text, True, (255, 240, 220))
        bg = pygame.Surface((surf.get_width() + 2 * pad, surf.get_height() + 2 * pad), pygame.SRCALPHA)
        bg.fill((20, 20, 20, 200))
        x = sw - bg.get_width() - margin
        screen.blit(bg, (x, y))
        screen.blit(surf, (x + pad, y + pad))
        y += bg.get_height() + 4


def _format_event(ev: dict) -> str:
    kind = ev.get("kind", "?")
    name = ev.get("player_name", "")
    if kind == "JOIN":
        return f"{name} joined."
    if kind == "LEAVE":
        return f"{name} left."
    if kind == "DISCONNECT":
        return f"{name} disconnected."
    if kind == "RECONNECT":
        return f"{name} reconnected."
    if kind == "KICK":
        by = ev.get("by_name", "host")
        return f"{name} was kicked by {by}."
    if kind == "REMOVED":
        reason = ev.get("reason", "")
        return f"{name} removed ({reason})."
    if kind == "HOST_MIGRATED":
        return f"{ev.get('new_host_name', '?')} is now the host."
    if kind == "REACTION_START":
        return "⚡ Reaction event!"
    if kind == "MATCH_START":
        return "Match started."
    if kind == "MATCH_END":
        suffix = " (walkover)" if ev.get("walkover") else ""
        return f"{ev.get('winner_name','?')} wins{suffix}!"
    return f"{kind}: {name}"


def run_app(server_host: str = "127.0.0.1", server_port: int = 5555,
            initial_name: str = "") -> None:
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    pygame.display.set_caption(f"Custom UNO Online — {server_host}:{server_port}")
    clock = pygame.time.Clock()

    network = SocketClientNetwork(server_host, server_port)
    try:
        network.connect()
    except OSError as exc:
        print(f"[client] cannot connect to {server_host}:{server_port}: {exc}")
        print("        start the server first with `python -m src.server`.")
        pygame.quit()
        return

    ctx = AppContext(network=network, assets=AssetManager())
    ctx.player_name = initial_name
    ctx.server_address = f"{server_host}:{server_port}"
    ctx.current_view = None
    ctx.views_by_player = {}
    ctx.toasts = []
    ctx.chat_log = []
    ctx.chat_input = ""
    ctx.chat_focus = False

    # ------------------------------------------------------------------
    # navigation callbacks
    # ------------------------------------------------------------------
    def go_menu() -> None:
        ctx.current_view = None
        ctx.player_id = ""
        ctx.room_code = ""
        ctx.chat_log = []
        ctx.chat_input = ""
        ctx.chat_focus = False
        ctx.chat_expanded = True
        scene_manager.switch(MenuScene(ctx, go_browser))

    def go_browser() -> None:
        ctx.error = ""
        ctx.chat_log = []
        ctx.chat_input = ""
        ctx.chat_focus = False
        ctx.chat_expanded = True
        scene_manager.switch(
            LobbyBrowserScene(ctx, on_create=do_create, on_join=do_join, on_back=go_menu)
        )

    def do_create() -> None:
        ctx.error = ""
        network.host_room(ctx.player_name or "Player")

    def do_join(code: str) -> None:
        ctx.error = ""
        network.join_room(code, ctx.player_name or "Player")

    def go_lobby() -> None:
        scene_manager.switch(LobbyScene(ctx, leave_lobby))

    def leave_lobby() -> None:
        # Tell server we're leaving the room (engine handles pre-/post-match).
        # Use the dedicated LEAVE_ROOM envelope — sending LeaveRoom via the
        # generic ACTION path would trip the server's kick-cleanup branch,
        # which closes our own socket.
        if ctx.player_id:
            network.leave_room()
        network.player_id = ""
        network.room_code = ""
        network.is_host = False
        ctx.current_view = None
        ctx.player_id = ""
        ctx.room_code = ""
        go_browser()

    def on_state(player_id, view) -> None:
        # In socket mode there's exactly one local player; just record their view.
        ctx.views_by_player[player_id] = view
        ctx.player_id = player_id
        ctx.room_code = view.room_code
        ctx.current_view = view

    network.on_state(on_state)
    scene_manager = SceneManager(MenuScene(ctx, go_browser))

    running = True
    while running:
        dt = clock.tick(60) / 1000.0
        network.update()

        # Surface async errors raised by network handlers (rejection / kicked).
        if network.last_error and not ctx.error:
            ctx.error = network.last_error
            network.last_error = ""

        # Drain transient EVENTs from the network and turn them into toasts.
        now_t = time.monotonic()
        while True:
            ev = network.pop_event()
            if ev is None:
                break
            if ev.get("kind") == "CHAT":
                name = ev.get("player_name", "Player")
                msg = str(ev.get("message", "")).strip()
                if msg:
                    ctx.chat_log.append((name, msg))
                    if len(ctx.chat_log) > 60:
                        ctx.chat_log = ctx.chat_log[-60:]
                continue
            ctx.toasts.append((_format_event(ev), now_t + 4.0))
        # Expire old toasts.
        ctx.toasts = [(t, exp) for (t, exp) in ctx.toasts if exp > now_t]

        # If we just got JOINED, the next STATE will populate the view; transition
        # into the lobby as soon as we know our player_id.
        if (
            network.player_id
            and ctx.current_view is not None
            and not isinstance(scene_manager.current, (LobbyScene, GameScene, EndGameScene))
        ):
            go_lobby()

        # Auto-route on view changes (started/ended).
        view = ctx.current_view
        if view is not None and network.player_id:
            if view.ended and not isinstance(scene_manager.current, EndGameScene):
                scene_manager.switch(EndGameScene(ctx, leave_lobby))
            elif view.started and not view.ended and not isinstance(scene_manager.current, GameScene):
                scene_manager.switch(GameScene(ctx))
            elif (not view.started) and isinstance(scene_manager.current, GameScene):
                scene_manager.switch(LobbyScene(ctx, leave_lobby))

        # If we lost our seat (kicked / connection ended), bounce back to browser.
        if (
            not network.player_id
            and isinstance(scene_manager.current, (LobbyScene, GameScene, EndGameScene))
        ):
            ctx.current_view = None
            go_browser()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                continue
            scene_manager.current.handle_event(event)

        scene_manager.current.update(dt)
        scene_manager.current.draw(screen)
        _draw_toasts(screen, ctx)
        pygame.display.flip()

    network.close()
    pygame.quit()
