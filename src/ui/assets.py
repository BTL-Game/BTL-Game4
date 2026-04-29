from __future__ import annotations

from pathlib import Path

import pygame

from src.core.cards import Card, CardType, Color
from src.ui.theme import BLUE, GREEN, RED, WILD_BLACK, YELLOW


SYMBOL = {
    CardType.SKIP: "Ø",        # Ø
    CardType.REVERSE: "↻",     # ↻
    CardType.DRAW_TWO: "+2",
    CardType.WILD: "W",
    CardType.WILD_DRAW_FOUR: "+4",
}


class AssetManager:
    def __init__(self, base_dir: str = "assets/cards") -> None:
        self.base = Path(base_dir)
        self.cache: dict[str, pygame.Surface] = {}

    def _color(self, color: Color) -> tuple[int, int, int]:
        return {
            Color.RED: RED,
            Color.GREEN: GREEN,
            Color.BLUE: BLUE,
            Color.YELLOW: YELLOW,
            Color.WILD: WILD_BLACK,
        }[color]

    def card_back(self, size: tuple[int, int] = (90, 135)) -> pygame.Surface:
        key = f"__back_{size[0]}x{size[1]}"
        if key in self.cache:
            return self.cache[key]
        surf = pygame.Surface(size, pygame.SRCALPHA)
        self._draw_card_base(surf, size, WILD_BLACK)
        # Red oval with "UNO" letters.
        ow, oh = int(size[0] * 0.78), int(size[1] * 0.34)
        ox = (size[0] - ow) // 2
        oy = (size[1] - oh) // 2
        pygame.draw.ellipse(surf, RED, (ox, oy, ow, oh))
        font = pygame.font.SysFont("arialblack,arial", int(size[1] * 0.20), bold=True, italic=True)
        txt = font.render("UNO", True, YELLOW)
        surf.blit(txt, txt.get_rect(center=(size[0] // 2, size[1] // 2)))
        self.cache[key] = surf
        return surf

    def card_surface(self, card: Card, size: tuple[int, int] = (90, 135)) -> pygame.Surface:
        key = f"{card.code()}_{size[0]}x{size[1]}"
        if key in self.cache:
            return self.cache[key]
        file = self.base / f"{card.code()}.png"
        if file.exists():
            try:
                img = pygame.image.load(str(file)).convert_alpha()
                surf = pygame.transform.smoothscale(img, size)
                self.cache[key] = surf
                return surf
            except Exception:
                pass
        surf = self._render_placeholder(card, size)
        self.cache[key] = surf
        return surf

    # --- placeholder painting ----------------------------------------

    def _draw_card_base(self, surf: pygame.Surface, size: tuple[int, int], face_color) -> None:
        w, h = size
        # White outer rounded card.
        pygame.draw.rect(surf, (250, 250, 245), (0, 0, w, h), border_radius=12)
        # Inner colored panel.
        pygame.draw.rect(surf, face_color, (4, 4, w - 8, h - 8), border_radius=10)
        # Center white tilted ellipse.
        ow, oh = int(w * 0.82), int(h * 0.62)
        ox = (w - ow) // 2
        oy = (h - oh) // 2
        pygame.draw.ellipse(surf, (250, 250, 245), (ox, oy, ow, oh))

    def _render_placeholder(self, card: Card, size: tuple[int, int]) -> pygame.Surface:
        w, h = size
        surf = pygame.Surface(size, pygame.SRCALPHA)
        face_color = self._color(card.color)
        if card.card_type in (CardType.WILD, CardType.WILD_DRAW_FOUR):
            self._draw_card_base(surf, size, WILD_BLACK)
            # Four-color quadrants in the central ellipse.
            cx, cy = w // 2, h // 2
            r = int(min(w, h) * 0.28)
            pygame.draw.polygon(surf, RED,    [(cx, cy), (cx + r, cy - r), (cx, cy - r)])
            pygame.draw.polygon(surf, YELLOW, [(cx, cy), (cx, cy - r), (cx - r, cy - r), (cx - r, cy)])
            pygame.draw.polygon(surf, GREEN,  [(cx, cy), (cx - r, cy), (cx - r, cy + r), (cx, cy + r)])
            pygame.draw.polygon(surf, BLUE,   [(cx, cy), (cx, cy + r), (cx + r, cy + r), (cx + r, cy)])
        else:
            self._draw_card_base(surf, size, face_color)

        label = self._label(card)
        # Big center label.
        big = pygame.font.SysFont("arialblack,arial", int(h * 0.42), bold=True)
        col = (250, 250, 245) if card.card_type in (CardType.WILD, CardType.WILD_DRAW_FOUR) else face_color
        txt = big.render(label, True, col)
        surf.blit(txt, txt.get_rect(center=(w // 2, h // 2)))

        # Small corner labels.
        small = pygame.font.SysFont("arialblack,arial", int(h * 0.13), bold=True)
        s_top = small.render(label, True, (250, 250, 245))
        s_bot = pygame.transform.rotate(s_top, 180)
        surf.blit(s_top, (6, 4))
        surf.blit(s_bot, (w - s_bot.get_width() - 6, h - s_bot.get_height() - 4))
        return surf

    def _label(self, card: Card) -> str:
        if card.card_type == CardType.NUMBER:
            return str(card.value)
        return SYMBOL.get(card.card_type, "?")
