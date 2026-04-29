from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Callable[[Any], None]]] = defaultdict(list)

    def subscribe(self, event_name: str, callback: Callable[[Any], None]) -> None:
        self._subs[event_name].append(callback)

    def publish(self, event_name: str, payload: Any) -> None:
        for cb in self._subs[event_name]:
            cb(payload)
