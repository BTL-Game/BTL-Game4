from dataclasses import dataclass


@dataclass
class Player:
    player_id: str
    name: str
    is_host: bool = False
