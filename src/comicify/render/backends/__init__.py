"""Output backends. Each turns a resolved Scene into files in an output directory.

To add a format (PDF, HTML slides, ...), implement `Backend` and register it.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from ..scene import Scene
from .pdf import PdfBackend
from .png import PngBackend
from .svg import FontMode, SvgBackend


class Backend(Protocol):
    name: str

    def render(self, scene: Scene, out_dir: Path) -> list[Path]: ...


BACKENDS: dict[str, Callable[[FontMode], Backend]] = {
    "svg": SvgBackend,
    "png": PngBackend,
    "pdf": PdfBackend,
}

__all__ = ["BACKENDS", "Backend", "FontMode"]
