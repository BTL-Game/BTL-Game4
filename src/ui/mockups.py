from __future__ import annotations

from pathlib import Path

import pygame

from src.core.cards import Card, CardType, Color
from src.core.deck import build_standard_uno_deck
from src.ui.assets import AssetManager


def generate(force: bool = False) -> None:
    pygame.init()
    out = Path("assets/cards")
    out.mkdir(parents=True, exist_ok=True)
    manager = AssetManager(str(out))
    deck = build_standard_uno_deck()
    unique: dict[str, Card] = {}
    for c in deck:
        unique[c.code()] = c
    for code, card in unique.items():
        file = out / f"{code}.png"
        if file.exists() and not force:
            continue
        surf = manager.card_surface(card, (100, 150))
        pygame.image.save(surf, str(file))
    pygame.quit()


if __name__ == "__main__":
    generate()
