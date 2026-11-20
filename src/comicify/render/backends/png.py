"""Scene → PNG, rasterized from the SVG output with resvg (bundled fonts only)."""

from __future__ import annotations

from pathlib import Path

import resvg_py

from ..scene import Scene
from .svg import FontMode, SvgWriter


class PngBackend:
    name = "png"

    def __init__(self, font_mode: FontMode = FontMode.OUTLINE, zoom: float = 1.0):
        self.writer = SvgWriter(font_mode)
        self.zoom = zoom

    def render(self, scene: Scene, out_dir: Path) -> list[Path]:
        fonts = sorted({str(f.path) for f in scene.fonts})
        paths = []
        for i, page in enumerate(scene.pages, 1):
            png = resvg_py.svg_to_bytes(
                svg_string=self.writer.write(page, scene),
                skip_system_fonts=True,  # never depend on the host's fonts
                font_files=fonts,
                zoom=self.zoom,
            )
            p = out_dir / f"page-{i:02d}.png"
            p.write_bytes(bytes(png))
            paths.append(p)
        return paths
