from __future__ import annotations

import pygame

from src.network.local import LocalNetwork
from src.ui.assets import AssetManager
from src.ui.scene import AppContext
from src.ui.scene_manager import SceneManager
from src.ui.scenes.end_game import EndGameScene
from src.ui.scenes.game import GameScene
from src.ui.scenes.lobby import LobbyScene
from src.ui.scenes.menu import MenuScene
from src.ui.theme import SCREEN_H, SCREEN_W


def run_app() -> None:
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    pygame.display.set_caption("Custom UNO Online")
    clock = pygame.time.Clock()

    network = LocalNetwork()
    ctx = AppContext(network=network, assets=AssetManager())
    ctx.player_name = "Player"
    ctx.current_view = None
    ctx.views_by_player = {}
    ctx.seated_player_ids = []  # hot-seat order

    def go_menu() -> None:
        scene_manager.switch(MenuScene(ctx, go_lobby))

    def go_lobby(create: bool) -> None:
        ctx.error = ""
        if create:
            host_id = network.host_room(ctx.player_name or "Host")
            ctx.player_id = host_id
            ctx.seated_player_ids = [host_id]
            # Auto-add 3 dummy seats so single-machine demo works.
            # Names are just labels; in real LAN play, real clients join instead.
            for nm in ("Bob", "Charlie", "Dave"):
                pid = network.join_room(network.engine.state.room_code, nm)
                if pid:
                    ctx.seated_player_ids.append(pid)
            network.update()
        else:
            if not network.engine.state.players:
                host_id = network.host_room("Host")
                ctx.seated_player_ids = [host_id]
            pid = network.join_room(network.engine.state.room_code,
                                    ctx.player_name or "Guest")
            if not pid:
                ctx.error = "Join failed (room full or game started)."
                return
            ctx.player_id = pid
            ctx.seated_player_ids.append(pid)
            network.update()
        scene_manager.switch(LobbyScene(ctx, go_menu))

    def on_state(player_id, view) -> None:
        ctx.views_by_player[player_id] = view

    def refresh_view() -> None:
        # Auto-follow whose turn it is during normal play, or the player who
        # owes a decision (color / direction / target). Keeps hot-seat usable.
        view = ctx.views_by_player.get(ctx.player_id)
        ctx.current_view = view

    network.on_state(on_state)
    scene_manager = SceneManager(MenuScene(ctx, go_lobby))
    running = True
    while running:
        dt = clock.tick(60) / 1000.0
        network.update()
        # Hot-seat: auto-switch active seat to whoever the engine is asking
        # for input from. Manual override via TAB still works.
        view = ctx.views_by_player.get(ctx.player_id)
        if view and view.started and not view.ended and not view.reaction_active:
            who = (view.awaiting_color_for_player
                   or view.awaiting_direction_for_player
                   or view.awaiting_target_for_player
                   or view.turn_player_id)
            if who and who != ctx.player_id and who in ctx.seated_player_ids:
                ctx.player_id = who
        refresh_view()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                continue
            if event.type == pygame.KEYDOWN and event.key == pygame.K_TAB:
                if ctx.seated_player_ids:
                    i = ctx.seated_player_ids.index(ctx.player_id) \
                        if ctx.player_id in ctx.seated_player_ids else -1
                    ctx.player_id = ctx.seated_player_ids[(i + 1) % len(ctx.seated_player_ids)]
                    refresh_view()
                continue
            scene_manager.current.handle_event(event)

        view = ctx.current_view
        if view is not None:
            if view.ended and not isinstance(scene_manager.current, EndGameScene):
                scene_manager.switch(EndGameScene(ctx, go_menu))
            elif view.started and not view.ended and not isinstance(scene_manager.current, GameScene):
                scene_manager.switch(GameScene(ctx))
            elif (not view.started) and not isinstance(
                scene_manager.current, (MenuScene, LobbyScene)
            ):
                scene_manager.switch(LobbyScene(ctx, go_menu))
        scene_manager.current.update(dt)
        scene_manager.current.draw(screen)
        pygame.display.flip()
    pygame.quit()
