from __future__ import annotations

from pathlib import Path
from typing import Iterable

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


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ASSETS_ROOT = PROJECT_ROOT / "assets"


class AssetManager:
    """Centralized image/sound loader with caching.

    The original project only loaded card PNGs from assets/cards.
    This version also supports the new folders that were added:

    - assets/cards/back.png
    - assets/scenes/*.jpg
    - assets/avatars/*.jpg
    - assets/buttons/*.png
    - assets/sounds/*.mp3
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        # Resolve assets relative to the project root instead of the current
        # terminal working directory. This fixes missing images/sounds when the
        # game is launched as `python path/to/main.py` from another folder.
        self.project_root = PROJECT_ROOT
        self.assets_root = ASSETS_ROOT
        self.base = self._resolve(base_dir or "assets/cards")
        self.cache: dict[str, object] = {}
        self.sound_enabled = True
        self.music_enabled = True

    # ------------------------------------------------------------------
    # generic loading helpers
    # ------------------------------------------------------------------
    def _resolve(self, path: str | Path) -> Path:
        p = Path(path)
        if p.is_absolute():
            return p

        candidates: list[Path] = []
        # Keep current-working-directory support for dev convenience.
        candidates.append(Path.cwd() / p)
        # Support paths written as "assets/...".
        if p.parts and p.parts[0] == "assets":
            candidates.append(self.project_root / p)
            candidates.append(self.assets_root / Path(*p.parts[1:]))
        else:
            # Support paths relative to project root or directly to assets/.
            candidates.append(self.project_root / p)
            candidates.append(self.assets_root / p)

        for candidate in candidates:
            if candidate.exists():
                return candidate
        # Return the most likely intended absolute path for clearer errors/cache keys.
        return candidates[1] if len(candidates) > 1 else p

    def first_existing(self, paths: Iterable[str | Path]) -> Path | None:
        for path in paths:
            p = self._resolve(path)
            if p.exists():
                return p
        return None

    def image(self, path: str | Path, size: tuple[int, int] | None = None) -> pygame.Surface:
        """Load any image and optionally scale it.

        Raises FileNotFoundError / pygame.error if unavailable; callers that use
        optional decorative assets should wrap this in try/except.
        """
        resolved = self._resolve(path)
        key = f"img:{resolved}:{size}"
        cached = self.cache.get(key)
        if isinstance(cached, pygame.Surface):
            return cached
        img = pygame.image.load(str(resolved)).convert_alpha()
        if size is not None:
            img = pygame.transform.smoothscale(img, size)
        self.cache[key] = img
        return img

    def image_first(self, paths: Iterable[str | Path], size: tuple[int, int] | None = None) -> pygame.Surface | None:
        found = self.first_existing(paths)
        if found is None:
            return None
        try:
            return self.image(found, size)
        except Exception:
            return None

    def circular_image(self, path: str | Path, size: int) -> pygame.Surface:
        """Load an image as a circular avatar surface."""
        resolved = self._resolve(path)
        key = f"circle:{resolved}:{size}"
        cached = self.cache.get(key)
        if isinstance(cached, pygame.Surface):
            return cached

        raw = self.image(resolved)
        w, h = raw.get_size()
        crop = min(w, h)
        src = pygame.Rect((w - crop) // 2, (h - crop) // 2, crop, crop)
        square = pygame.Surface((crop, crop), pygame.SRCALPHA)
        square.blit(raw, (0, 0), src)
        square = pygame.transform.smoothscale(square, (size, size))

        mask = pygame.Surface((size, size), pygame.SRCALPHA)
        pygame.draw.circle(mask, (255, 255, 255, 255), (size // 2, size // 2), size // 2)
        square.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        self.cache[key] = square
        return square

    # ------------------------------------------------------------------
    # sound helpers
    # ------------------------------------------------------------------
    def ensure_audio(self) -> bool:
        if pygame.mixer.get_init():
            return True
        try:
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
            pygame.mixer.set_num_channels(16)
            return True
        except Exception:
            return False

    def sound(self, path: str | Path) -> pygame.mixer.Sound | None:
        if not self.sound_enabled or not self.ensure_audio():
            return None
        resolved = self._resolve(path)
        key = f"snd:{resolved}"
        cached = self.cache.get(key)
        if isinstance(cached, pygame.mixer.Sound):
            return cached
        if not resolved.exists():
            return None
        try:
            snd = pygame.mixer.Sound(str(resolved))
        except Exception:
            return None
        self.cache[key] = snd
        return snd

    def play_sound(self, *paths: str | Path, volume: float = 0.55) -> None:
        if not self.sound_enabled:
            return
        for path in paths:
            snd = self.sound(path)
            if snd is not None:
                try:
                    snd.set_volume(volume)
                    snd.play()
                except Exception:
                    pass
                return

    def play_music(self, paths: Iterable[str | Path], volume: float = 0.25, loops: int = -1) -> None:
        if not self.music_enabled or not self.ensure_audio():
            return
        found = self.first_existing(paths)
        if found is None:
            return
        try:
            pygame.mixer.music.load(str(found))
            pygame.mixer.music.set_volume(volume)
            pygame.mixer.music.play(loops)
        except Exception:
            # Some machines/pygame builds may not support a particular codec.
            pass

    def set_sound_enabled(self, enabled: bool) -> None:
        self.sound_enabled = enabled
        if not enabled and pygame.mixer.get_init():
            try:
                pygame.mixer.stop()
            except Exception:
                pass

    def set_music_enabled(self, enabled: bool) -> None:
        self.music_enabled = enabled
        if not pygame.mixer.get_init():
            return
        try:
            if enabled:
                pygame.mixer.music.unpause()
            else:
                pygame.mixer.music.pause()
        except Exception:
            pass

    def toggle_sound(self) -> bool:
        self.set_sound_enabled(not self.sound_enabled)
        return self.sound_enabled

    def toggle_music(self) -> bool:
        self.set_music_enabled(not self.music_enabled)
        return self.music_enabled

    # ------------------------------------------------------------------
    # card loading
    # ------------------------------------------------------------------
    def _color(self, color: Color) -> tuple[int, int, int]:
        return {
            Color.RED: RED,
            Color.GREEN: GREEN,
            Color.BLUE: BLUE,
            Color.YELLOW: YELLOW,
            Color.WILD: WILD_BLACK,
        }[color]

    def _card_file_candidates(self, code: str) -> list[Path]:
        candidates = [self.base / f"{code}.png"]
        # New asset pack uses *_draw_2.png while the engine code emits *_draw_two.png.
        if code.endswith("_draw_two"):
            candidates.append(self.base / f"{code.removesuffix('_draw_two')}_draw_2.png")
        # New asset pack uses wild_wild_draw_4.png while the engine emits wild_wild_draw_four.png.
        if code == "wild_wild_draw_four":
            candidates.append(self.base / "wild_wild_draw_4.png")
        return candidates

    def card_back(self, size: tuple[int, int] = (90, 135)) -> pygame.Surface:
        key = f"__back_{size[0]}x{size[1]}"
        cached = self.cache.get(key)
        if isinstance(cached, pygame.Surface):
            return cached

        back_file = self.first_existing([
            self.base / "back.png",
            self.base / "card_back.png",
            "assets/cards/back.png",
            "assets/cards/card_back.png",
        ])
        if back_file is not None:
            try:
                surf = self.image(back_file, size)
                self.cache[key] = surf
                return surf
            except Exception:
                pass

        # Fallback: old code-drawn card back.
        surf = pygame.Surface(size, pygame.SRCALPHA)
        self._draw_card_base(surf, size, WILD_BLACK)
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
        cached = self.cache.get(key)
        if isinstance(cached, pygame.Surface):
            return cached

        for file in self._card_file_candidates(card.code()):
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

    # ------------------------------------------------------------------
    # placeholder painting
    # ------------------------------------------------------------------
    def _draw_card_base(self, surf: pygame.Surface, size: tuple[int, int], face_color) -> None:
        w, h = size
        pygame.draw.rect(surf, (250, 250, 245), (0, 0, w, h), border_radius=12)
        pygame.draw.rect(surf, face_color, (4, 4, w - 8, h - 8), border_radius=10)
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
            cx, cy = w // 2, h // 2
            r = int(min(w, h) * 0.28)
            pygame.draw.polygon(surf, RED,    [(cx, cy), (cx + r, cy - r), (cx, cy - r)])
            pygame.draw.polygon(surf, YELLOW, [(cx, cy), (cx, cy - r), (cx - r, cy - r), (cx - r, cy)])
            pygame.draw.polygon(surf, GREEN,  [(cx, cy), (cx - r, cy), (cx - r, cy + r), (cx, cy + r)])
            pygame.draw.polygon(surf, BLUE,   [(cx, cy), (cx, cy + r), (cx + r, cy + r), (cx + r, cy)])
        else:
            self._draw_card_base(surf, size, face_color)

        label = self._label(card)
        big = pygame.font.SysFont("arialblack,arial", int(h * 0.42), bold=True)
        col = (250, 250, 245) if card.card_type in (CardType.WILD, CardType.WILD_DRAW_FOUR) else face_color
        txt = big.render(label, True, col)
        surf.blit(txt, txt.get_rect(center=(w // 2, h // 2)))

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
