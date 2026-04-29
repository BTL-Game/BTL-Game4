from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Envelope:
    msg_type: str
    payload: dict[str, Any]
