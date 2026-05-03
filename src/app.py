from __future__ import annotations

import time

import pygame

from src.network.server_probe import DEFAULT_SERVERS, ServerEntry, ServerProbe
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
_ALERT_FONT = None


def _friendly_reason(reason: str) -> str:
    r = reason.strip()
    low = r.lower()
    if "must stack +4 on +4" in low:
        return "Only +4 stacks on a +4 chain"
    if "must stack +2 or +4" in low:
        return "Stack +2/+4 or DRAW"
    if "not legally playable" in low:
        return "You can't play this card"
    if "cannot win with an action" in low:
        return "Can't win on an action card"
    if "not your turn" in low:
        return "Not your turn"
    if "invalid card index" in low:
        return "Invalid card"
    return r


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


def _draw_alert(screen: pygame.Surface, ctx: AppContext) -> None:
    global _ALERT_FONT
    alert = getattr(ctx, "alert", None)
    if not alert:
        return
    text, exp = alert
    if time.monotonic() > exp:
        ctx.alert = None
        return
    if _ALERT_FONT is None:
        _ALERT_FONT = pygame.font.SysFont("arialblack,arial", 22, bold=True)
    pad_x, pad_y = 18, 10
    surf = _ALERT_FONT.render(text, True, (255, 255, 255))
    sw = screen.get_width()
    bg = pygame.Surface(
        (surf.get_width() + 2 * pad_x, surf.get_height() + 2 * pad_y), pygame.SRCALPHA
    )
    bg.fill((200, 30, 30, 235))
    pygame.draw.rect(bg, (255, 220, 220), bg.get_rect(), 2, border_radius=8)
    x = (sw - bg.get_width()) // 2
    y = 64
    screen.blit(bg, (x, y))
    screen.blit(surf, (x + pad_x, y + pad_y))


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
    pygame.display.set_caption("Custom UNO Online")
    clock = pygame.time.Clock()

    # Build the advertised server list. If the CLI override doesn't match a
    # preset, append it as a "Custom" entry and pre-select it.
    servers: list[ServerEntry] = list(DEFAULT_SERVERS)
    selected_id = servers[0].id if servers else ""
    cli_match = next(
        (s for s in servers if s.host == server_host and s.port == server_port), None
    )
    if cli_match is not None:
        selected_id = cli_match.id
    elif (server_host, server_port) != ("127.0.0.1", 5555):
        custom = ServerEntry(id="custom", label=f"Custom ({server_host}:{server_port})",
                             host=server_host, port=server_port)
        servers.append(custom)
        selected_id = custom.id

    probe = ServerProbe(servers)
    probe.start()

    ctx = AppContext(network=None, assets=AssetManager())
    ctx.player_name = initial_name
    ctx.server_address = ""
    ctx.current_view = None
    ctx.views_by_player = {}
    ctx.toasts = []
    ctx.chat_log = []
    ctx.chat_input = ""
    ctx.chat_focus = False
    ctx.alert = None

    network: SocketClientNetwork | None = None

    # ------------------------------------------------------------------
    # navigation callbacks
    # ------------------------------------------------------------------
    def make_menu() -> MenuScene:
        return MenuScene(
            ctx, on_continue=connect_and_continue,
            servers=servers, probe=probe, selected_id=selected_id,
        )

    def go_menu() -> None:
        nonlocal network
        ctx.current_view = None
        ctx.player_id = ""
        ctx.room_code = ""
        ctx.chat_log = []
        ctx.chat_input = ""
        ctx.chat_focus = False
        ctx.chat_expanded = True
        ctx.error = ""
        if network is not None:
            try:
                network.close()
            except Exception:
                pass
            network = None
            ctx.network = None
        ctx.server_address = ""
        pygame.display.set_caption("Custom UNO Online")
        scene_manager.switch(make_menu())

    def connect_and_continue(entry: ServerEntry) -> None:
        nonlocal network, selected_id
        selected_id = entry.id
        ctx.error = ""
        net = SocketClientNetwork(entry.host, entry.port)
        try:
            net.connect()
        except OSError as exc:
            ctx.error = f"Cannot reach {entry.label}: {exc}"
            return
        net.on_state(on_state)
        network = net
        ctx.network = net
        ctx.server_address = f"{entry.host}:{entry.port}"
        pygame.display.set_caption(f"Custom UNO Online — {entry.label}")
        go_browser()

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
        if network is None:
            return
        ctx.error = ""
        network.host_room(ctx.player_name or "Player")

    def do_join(code: str) -> None:
        if network is None:
            return
        ctx.error = ""
        network.join_room(code, ctx.player_name or "Player")

    def go_lobby() -> None:
        scene_manager.switch(LobbyScene(ctx, leave_lobby))

    def leave_lobby() -> None:
        # Tell server we're leaving the room (engine handles pre-/post-match).
        # Use the dedicated LEAVE_ROOM envelope — sending LeaveRoom via the
        # generic ACTION path would trip the server's kick-cleanup branch,
        # which closes our own socket.
        if network is not None and ctx.player_id:
            network.leave_room()
        if network is not None:
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

    scene_manager = SceneManager(make_menu())

    running = True
    while running:
        dt = clock.tick(60) / 1000.0
        if network is not None:
            network.update()

            # Surface async errors raised by network handlers (rejection / kicked).
            if network.last_error:
                if isinstance(scene_manager.current, GameScene):
                    ctx.alert = (f"⚠ {_friendly_reason(network.last_error)}", time.monotonic() + 3.0)
                    network.last_error = ""
                elif not ctx.error:
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
            ctx.toasts = [(t, exp) for (t, exp) in ctx.toasts if exp > now_t]

            if (
                network.player_id
                and ctx.current_view is not None
                and not isinstance(scene_manager.current, (LobbyScene, GameScene, EndGameScene))
            ):
                go_lobby()

            view = ctx.current_view
            if view is not None and network.player_id:
                if view.ended and not isinstance(scene_manager.current, EndGameScene):
                    scene_manager.switch(EndGameScene(ctx, leave_lobby))
                elif view.started and not view.ended and not isinstance(scene_manager.current, GameScene):
                    scene_manager.switch(GameScene(ctx))
                elif (not view.started) and isinstance(scene_manager.current, GameScene):
                    scene_manager.switch(LobbyScene(ctx, leave_lobby))

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
        _draw_alert(screen, ctx)
        pygame.display.flip()

    if network is not None:
        network.close()
    probe.stop()
    pygame.quit()
