"""Visual style: palettes, pens, typography. Everything explicit, nothing implied.

Note: LLM-facing models use lists of records rather than open-ended maps
(`dict[str, ...]`); constrained decoding cannot express arbitrary keys.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from .base import Artifact, HexColor, Model, Slug


class NamedColor(Model):
    name: Slug
    hex: HexColor


class Palette(Model):
    id: Slug
    usage: str = Field(description="Where this palette applies, e.g. 'meadow set, daytime'.")
    colors: list[NamedColor]


class LineStyle(StrEnum):
    CLEAN = "clean"
    SKETCHY = "sketchy"  # deterministic jitter, seeded
    BRUSH = "brush"


class Pen(Model):
    id: Slug
    width: float = Field(gt=0, description="Stroke width in points at 1x.")
    color: str = Field(description="Palette color name, e.g. 'ink'.")
    style: LineStyle = LineStyle.CLEAN
    usage: str


class TextRole(StrEnum):
    DIALOGUE = "dialogue"
    CAPTION = "caption"
    SFX = "sfx"
    DEVICE = "device"  # text on subject-product screens/notifications
    TITLE = "title"


class Style(Artifact):
    """A look's concrete colors and pens, derived from an art pack and the storyboard.

    Palette ids follow a convention the renderer and illustrators rely on:
    `base`, `device`, `character-<id>` per character, `set-<id>` per set.
    """

    KIND = "style"

    summary: str = Field(description="One paragraph of art direction for this comic.")
    palettes: list[Palette]
    pens: list[Pen]
