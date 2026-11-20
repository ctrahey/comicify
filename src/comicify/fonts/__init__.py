"""Bundled fonts: registry, metrics, and glyph outlines.

Comics depend on lettering, and lettering must render identically everywhere.
So Comicify only uses fonts it ships (open-licensed), measures text with the
font's own metrics, and by default converts glyphs to outlines in the output.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property, lru_cache
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

FONTS_DIR = Path(__file__).parent


@dataclass(frozen=True)
class FontFace:
    family: str
    weight: int
    path: Path
    license: Path
    role_hint: str  # what the face is good for, shown to the style stage

    @property
    def key(self) -> str:
        return f"{self.family.lower().replace(' ', '-')}-{self.weight}"


class FontRegistry:
    def __init__(self, faces: list[FontFace]):
        self.faces = faces

    def families(self) -> list[dict[str, str]]:
        seen: dict[str, dict[str, str]] = {}
        for f in self.faces:
            entry = seen.setdefault(f.family, {"family": f.family, "weights": "", "use": f.role_hint})
            entry["weights"] = ", ".join(filter(None, [entry["weights"], str(f.weight)]))
        return list(seen.values())

    def has_family(self, family: str) -> bool:
        return any(f.family == family for f in self.faces)

    def resolve(self, family: str, weight: int = 400) -> FontFace:
        candidates = [f for f in self.faces if f.family == family]
        if not candidates:
            raise KeyError(f"Font family {family!r} is not bundled")
        return min(candidates, key=lambda f: abs(f.weight - weight))


def _face(family: str, weight: int, folder: str, file: str, use: str) -> FontFace:
    return FontFace(family, weight, FONTS_DIR / folder / file, FONTS_DIR / folder / "OFL.txt", use)


# All bundled faces are SIL Open Font License 1.1 (from github.com/google/fonts).
# Variable fonts were baked into static instances so weights are deterministic.
REGISTRY = FontRegistry([
    _face("Comic Neue", 400, "comic-neue", "ComicNeue-Regular.ttf", "dialogue, captions"),
    _face("Comic Neue", 700, "comic-neue", "ComicNeue-Bold.ttf", "dialogue, captions"),
    _face("Bangers", 400, "bangers", "Bangers-Regular.ttf", "titles, sound effects (caps)"),
    _face("Patrick Hand", 400, "patrickhand", "PatrickHand-Regular.ttf", "hand lettering"),
    _face("Kalam", 400, "kalam", "Kalam-Regular.ttf", "marker / handwriting"),
    _face("Kalam", 700, "kalam", "Kalam-Bold.ttf", "marker / handwriting"),
    _face("Work Sans", 400, "worksans", "WorkSans-Regular.ttf", "clean modern sans"),
    _face("Work Sans", 700, "worksans", "WorkSans-Bold.ttf", "clean modern sans"),
    _face("Poppins", 400, "poppins", "Poppins-Regular.ttf", "geometric product sans"),
    _face("Poppins", 600, "poppins", "Poppins-SemiBold.ttf", "geometric product sans"),
    _face("Fredoka", 400, "fredoka", "Fredoka-Regular.ttf", "rounded playful"),
    _face("Fredoka", 600, "fredoka", "Fredoka-SemiBold.ttf", "rounded playful"),
    _face("Archivo Black", 400, "archivoblack", "ArchivoBlack-Regular.ttf", "heavy display"),
    _face("Space Mono", 400, "spacemono", "SpaceMono-Regular.ttf", "zine / typewriter mono"),
    _face("Space Mono", 700, "spacemono", "SpaceMono-Bold.ttf", "zine / typewriter mono"),
    _face("Libre Caslon Text", 400, "librecaslontext", "LibreCaslonText-Regular.ttf",
          "editorial serif"),
    _face("Libre Caslon Text", 700, "librecaslontext", "LibreCaslonText-Bold.ttf",
          "editorial serif"),
    _face("JetBrains Mono", 400, "jetbrainsmono", "JetBrainsMono-Regular.ttf", "code"),
    _face("JetBrains Mono", 700, "jetbrainsmono", "JetBrainsMono-Bold.ttf", "code"),
])


class FontMetrics:
    """Advance widths and outlines for one face. Units are px at the given size."""

    def __init__(self, path: Path):
        self._font = TTFont(path, lazy=True)
        self.upm: int = self._font["head"].unitsPerEm
        self._cmap = self._font.getBestCmap()
        self._hmtx = self._font["hmtx"]
        hhea = self._font["hhea"]
        self.ascent_units: int = hhea.ascent
        self.descent_units: int = hhea.descent  # negative

    @cached_property
    def _glyph_set(self):
        return self._font.getGlyphSet()

    def has_glyph(self, ch: str) -> bool:
        return ord(ch) in self._cmap

    def glyph_name(self, ch: str) -> str:
        return self._cmap.get(ord(ch)) or self._cmap.get(ord("?")) or ".notdef"

    def advance(self, ch: str, size: float) -> float:
        return self._hmtx[self.glyph_name(ch)][0] * size / self.upm

    def width(self, text: str, size: float) -> float:
        return sum(self.advance(c, size) for c in text)

    def ascent(self, size: float) -> float:
        return self.ascent_units * size / self.upm

    def descent(self, size: float) -> float:
        return -self.descent_units * size / self.upm

    def line_height(self, size: float, leading: float = 1.15) -> float:
        return (self.ascent(size) + self.descent(size)) * leading

    @lru_cache(maxsize=4096)  # noqa: B019 — instances are cached per face for the process
    def outline(self, glyph: str) -> str:
        """SVG path data for a glyph in font units (y up)."""
        pen = SVGPathPen(self._glyph_set)
        self._glyph_set[glyph].draw(pen)
        return pen.getCommands()


@lru_cache(maxsize=None)
def metrics(face: FontFace) -> FontMetrics:
    return FontMetrics(face.path)
