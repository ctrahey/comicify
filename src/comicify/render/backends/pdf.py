"""Scene → PDF: one landscape page per scene page.

Pages are rasterized with resvg at 2× and embedded losslessly, so the PDF is
pixel-identical to the PNG output, filters and all. (A vector PDF needs an
SVG→PDF engine with full filter support; that's a future backend.)
"""

from __future__ import annotations

from pathlib import Path

import img2pdf
import resvg_py

from ..scene import Scene
from .svg import FontMode, SvgWriter


class PdfBackend:
    name = "pdf"

    def __init__(self, font_mode: FontMode = FontMode.OUTLINE, zoom: float = 2.0):
        self.writer = SvgWriter(font_mode)
        self.zoom = zoom

    def render(self, scene: Scene, out_dir: Path) -> list[Path]:
        fonts = sorted({str(f.path) for f in scene.fonts})
        images = [bytes(resvg_py.svg_to_bytes(svg_string=self.writer.write(page, scene),
                                              skip_system_fonts=True, font_files=fonts,
                                              zoom=self.zoom))
                  for page in scene.pages]
        first = scene.pages[0]
        # Page size in points at 96 dpi-equivalent: keeps physical proportions sane.
        layout = img2pdf.get_layout_fun((img2pdf.px_to_pt(first.width, 96),
                                         img2pdf.px_to_pt(first.height, 96)))
        out = out_dir / "comic.pdf"
        out.write_bytes(img2pdf.convert(images, layout_fun=layout))
        return [out]
