from __future__ import annotations

from .scene import Scene


class SceneManager:
    def __init__(self, first_scene: Scene) -> None:
        self.current = first_scene

    def switch(self, next_scene: Scene) -> None:
        self.current = next_scene
