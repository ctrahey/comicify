"""The resolved scene graph: what compose produces and backends consume.

Everything here is absolute and final: page-space geometry, hex colors, text
already shaped into positioned lines with a concrete font face. Backends make
no layout decisions; they only serialize.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..fonts import FontFace
from ..models.direction import Grain, Halftone, Misregister, Monochrome, Posterize, Wobble


@dataclass(frozen=True)
class Paint:
    fill: str = "none"
    stroke: str | None = None
    width: float = 0.0
    dash: str | None = None
    opacity: float = 1.0
    linejoin: str = "round"


@dataclass
class Rect:
    x: float
    y: float
    w: float
    h: float
    paint: Paint
    rx: float = 0.0


@dataclass
class Ellipse:
    cx: float
    cy: float
    rx: float
    ry: float
    paint: Paint


@dataclass
class PathNode:
    d: str
    paint: Paint


@dataclass
class Asset:
    """A frozen SVG asset placed into a box (its viewBox is scaled to fit)."""

    ref: str  # unique symbol id within a page
    source: Path
    x: float
    y: float
    w: float
    h: float
    mirror: bool = False


@dataclass
class TextLine:
    x: float  # left edge of the line
    y: float  # baseline
    text: str


@dataclass
class Text:
    lines: list[TextLine]
    face: FontFace
    size: float
    fill: str
    outline: Paint | None = None  # e.g. a white halo behind sound effects
    rotate: tuple[float, float, float] | None = None  # (degrees, cx, cy)


GroupEffect = Monochrome | Posterize | Wobble | Misregister


@dataclass
class Overlay:
    """A texture laid over a region (halftone dots, paper grain)."""

    x: float
    y: float
    w: float
    h: float
    effect: Halftone | Grain
    scale: float = 1.0  # page scale relative to 1080px, for px-based effect parameters


@dataclass
class Group:
    children: list[Node] = field(default_factory=list)
    clip: Rect | None = None
    transform: str | None = None
    label: str | None = None  # becomes the group's id, for debugging and editing
    effects: list[GroupEffect] = field(default_factory=list)  # applied in order

    def add(self, *nodes: Node) -> None:
        self.children.extend(nodes)


Node = Rect | Ellipse | PathNode | Asset | Text | Overlay | Group


@dataclass
class ScenePage:
    id: str
    width: int
    height: int
    background: str
    root: Group

    def walk(self):
        stack: list[Node] = [self.root]
        while stack:
            node = stack.pop()
            yield node
            if isinstance(node, Group):
                stack.extend(reversed(node.children))


@dataclass
class Scene:
    pages: list[ScenePage]
    fonts: list[FontFace]
