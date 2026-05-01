from dataclasses import dataclass


@dataclass
class Player:
    player_id: str
    name: str
    is_host: bool = False
    joined_at: float = 0.0
    connected: bool = True
    disconnected_at: float | None = None
    total_disconnect_seconds: float = 0.0
