"""Resolves a look into concrete render values.

  art pack        lettering, ink, paper, balloon and panel styling, effects
  style.yaml      this comic's palettes and pens (per look)
  cinematography  gutters and grid rhythm
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import ArtPack, CinematographyPack, Style
from ..models.style import TextRole
from .scene import Paint
from .text import Font

DEFAULT_COLORS = {
    "device-bg": "#1e2230", "device-text": "#f3f5fa", "device-accent": "#4cc2ff",
    "device-alert": "#ff5a4e", "placeholder": "#c9ccd3",
}


def fallback_style(art: ArtPack) -> Style:
    """A deterministic stand-in for a look's style.yaml, from the art pack alone.

    Used when rendering before the style stage has run (e.g. a blocking pass).
    """
    from ..models.style import NamedColor, Palette, Pen

    anchors = art.color.anchors or ["#9cc9e8", "#9bc46b"]
    return Style(
        summary=f"Fallback colors from the {art.name} pack.",
        palettes=[Palette(id="base", usage="fallback", colors=[
            NamedColor(name="ink", hex=art.panel.ink), NamedColor(name="paper", hex=art.panel.paper),
            NamedColor(name="sky", hex=anchors[0]),
            NamedColor(name="ground", hex=anchors[min(1, len(anchors) - 1)])])],
        pens=[Pen(id="outline", width=art.line.weight_px, color="ink", usage="fallback")],
    )


@dataclass
class Theme:
    style: Style
    art: ArtPack
    cine: CinematographyPack

    def __post_init__(self) -> None:
        self._colors: dict[str, str] = {}
        for palette in self.style.palettes:
            for c in palette.colors:
                self._colors.setdefault(c.name, c.hex)
        self._pens = {p.id: p for p in self.style.pens}
        self._palettes = {p.id: p for p in self.style.palettes}

    # --- colors ----------------------------------------------------------------
    @property
    def ink(self) -> str:
        return self.art.panel.ink

    @property
    def paper(self) -> str:
        return self.art.panel.paper

    def color(self, name: str, fallback: str | None = None) -> str:
        if name.startswith("#"):
            return name
        return self._colors.get(name) or DEFAULT_COLORS.get(name) or fallback or self.ink

    def palette_color(self, palette_id: str, *hints: str, fallback: str) -> str:
        """First color in a palette whose name contains any hint (in hint order)."""
        palette = self._palettes.get(palette_id)
        if palette:
            for hint in hints:
                for c in palette.colors:
                    if hint in c.name:
                        return c.hex
        return self.color(fallback)

    def set_sky(self, set_id: str) -> str:
        return self.palette_color(f"set-{set_id}", "sky", fallback=self.paper)

    # --- lettering and panels --------------------------------------------------
    def font(self, role: TextRole, scale: float = 1.0) -> Font:
        choice = getattr(self.art.lettering, TextRole(role).value)
        return Font.from_choice(choice, scale)

    @property
    def balloon_fill(self) -> str:
        return self.art.lettering.balloon_fill

    @property
    def caption_fill(self) -> str:
        return self.art.lettering.caption_fill

    def panel_border(self, scale: float) -> Paint | None:
        w = self.art.panel.border_px * scale
        return Paint(stroke=self.art.panel.border or self.ink, width=w) if w > 0.2 else None

    @property
    def dark(self) -> bool:
        """A dark look (light ink on a dark field)."""
        h = self.paper.lstrip("#")
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.35

    def gutter(self, scale: float) -> float:
        return self.cine.grid.gutter_px * scale

    # --- device UI -------------------------------------------------------------
    @property
    def device_bg(self) -> str:
        return self.palette_color("device", "bg", "background", "screen", fallback="device-bg")

    @property
    def device_text(self) -> str:
        return self.palette_color("device", "text", "fg", "foreground", fallback="device-text")

    @property
    def device_accent(self) -> str:
        return self.palette_color("device", "accent", "highlight", fallback="device-accent")

    @property
    def device_alert(self) -> str:
        return self.palette_color("device", "alert", "warn", "danger", fallback="device-alert")
