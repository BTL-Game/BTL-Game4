"""JSON ↔ domain object codec for the wire protocol.

Wire-protocol policy:
- Every TCP message is one JSON object terminated by `\n`.
- Outer envelope: {"type": "<MSG>", "payload": {...}}.
- Inner payloads here cover Card, Action, GameStateView.
"""
from __future__ import annotations

from typing import Any

from src.core.actions import (
    ChooseColor,
    ChooseDirection,
    ChooseTarget,
    DrawCard,
    KickPlayer,
    AddBot,
    LeaveRoom,
    PlayCard,
    Reaction,
    DeclareUno,
    StartMatch,
)
from src.core.cards import Card, CardType, Color
from src.core.game_state import GameStateView, PublicPlayerView


# ---------------------------------------------------------------------------
# Card
# ---------------------------------------------------------------------------
def card_to_json(c: Card | None) -> dict[str, Any] | None:
    if c is None:
        return None
    return {"color": c.color.value, "card_type": c.card_type.value, "value": c.value}


def card_from_json(d: dict[str, Any] | None) -> Card | None:
    if d is None:
        return None
    return Card(
        color=Color(d["color"]),
        card_type=CardType(d["card_type"]),
        value=d.get("value"),
    )


# ---------------------------------------------------------------------------
# GameStateView
# ---------------------------------------------------------------------------
def player_view_to_json(p: PublicPlayerView) -> dict[str, Any]:
    return {
        "player_id": p.player_id,
        "name": p.name,
        "is_host": p.is_host,
        "card_count": p.card_count,
        "connected": p.connected,
        "disconnect_seconds": p.disconnect_seconds,
    }


def player_view_from_json(d: dict[str, Any]) -> PublicPlayerView:
    return PublicPlayerView(
        player_id=d["player_id"],
        name=d["name"],
        is_host=d["is_host"],
        card_count=d["card_count"],
        connected=d.get("connected", True),
        disconnect_seconds=d.get("disconnect_seconds", 0.0),
    )


def view_to_json(v: GameStateView) -> dict[str, Any]:
    return {
        "self_player_id": v.self_player_id,
        "players": [player_view_to_json(p) for p in v.players],
        "self_hand": [card_to_json(c) for c in v.self_hand],
        "top_card": card_to_json(v.top_card),
        "current_color": v.current_color.value if v.current_color else None,
        "turn_player_id": v.turn_player_id,
        "direction": v.direction,
        "pending_penalty": v.pending_penalty,
        "pending_penalty_min": v.pending_penalty_min,
        "started": v.started,
        "ended": v.ended,
        "winner_id": v.winner_id,
        "draw_count": v.draw_count,
        "room_code": v.room_code,
        "awaiting_color_for_player": v.awaiting_color_for_player,
        "awaiting_direction_for_player": v.awaiting_direction_for_player,
        "awaiting_target_for_player": v.awaiting_target_for_player,
        "may_play_drawn_for_player": v.may_play_drawn_for_player,
        "reaction_active": v.reaction_active,
        "reaction_time_left": v.reaction_time_left,
        "reaction_responded_ids": list(v.reaction_responded_ids),
        "log": list(v.log),
    }


def view_from_json(d: dict[str, Any]) -> GameStateView:
    return GameStateView(
        self_player_id=d["self_player_id"],
        players=[player_view_from_json(p) for p in d["players"]],
        self_hand=[card_from_json(c) for c in d["self_hand"]],
        top_card=card_from_json(d.get("top_card")),
        current_color=Color(d["current_color"]) if d.get("current_color") else None,
        turn_player_id=d.get("turn_player_id"),
        direction=d["direction"],
        pending_penalty=d["pending_penalty"],
        pending_penalty_min=d["pending_penalty_min"],
        started=d["started"],
        ended=d["ended"],
        winner_id=d.get("winner_id"),
        draw_count=d["draw_count"],
        room_code=d["room_code"],
        awaiting_color_for_player=d.get("awaiting_color_for_player"),
        awaiting_direction_for_player=d.get("awaiting_direction_for_player"),
        awaiting_target_for_player=d.get("awaiting_target_for_player"),
        may_play_drawn_for_player=d.get("may_play_drawn_for_player"),
        reaction_active=d["reaction_active"],
        reaction_time_left=d["reaction_time_left"],
        reaction_responded_ids=list(d.get("reaction_responded_ids", [])),
        log=list(d.get("log", [])),
    )


# ---------------------------------------------------------------------------
# Action
# ---------------------------------------------------------------------------
def action_to_json(action: object) -> dict[str, Any]:
    if isinstance(action, PlayCard):
        return {"action_type": "PlayCard", "hand_index": action.hand_index}
    if isinstance(action, DrawCard):
        return {"action_type": "DrawCard"}
    if isinstance(action, ChooseColor):
        return {"action_type": "ChooseColor", "color": action.color.value}
    if isinstance(action, ChooseDirection):
        return {"action_type": "ChooseDirection", "direction": action.direction}
    if isinstance(action, ChooseTarget):
        return {"action_type": "ChooseTarget", "target_player_id": action.target_player_id}
    if isinstance(action, Reaction):
        return {"action_type": "Reaction"}
    if isinstance(action, DeclareUno):
        return {"action_type": "DeclareUno"}
    if isinstance(action, StartMatch):
        return {"action_type": "StartMatch"}
    if isinstance(action, LeaveRoom):
        return {"action_type": "LeaveRoom"}
    if isinstance(action, KickPlayer):
        return {"action_type": "KickPlayer", "target_player_id": action.target_player_id}
    if isinstance(action, AddBot):
        return {"action_type": "AddBot"}
    raise ValueError(f"Unknown action type: {type(action).__name__}")


def action_from_json(d: dict[str, Any]) -> object:
    t = d.get("action_type")
    if t == "PlayCard":
        return PlayCard(hand_index=int(d["hand_index"]))
    if t == "DrawCard":
        return DrawCard()
    if t == "ChooseColor":
        return ChooseColor(color=Color(d["color"]))
    if t == "ChooseDirection":
        return ChooseDirection(direction=int(d["direction"]))
    if t == "ChooseTarget":
        return ChooseTarget(target_player_id=str(d["target_player_id"]))
    if t == "Reaction":
        return Reaction()
    if t == "DeclareUno":
        return DeclareUno()
    if t == "StartMatch":
        return StartMatch()
    if t == "LeaveRoom":
        return LeaveRoom()
    if t == "KickPlayer":
        return KickPlayer(target_player_id=str(d["target_player_id"]))
    if t == "AddBot":
        return AddBot()
    raise ValueError(f"Unknown action_type: {t!r}")
