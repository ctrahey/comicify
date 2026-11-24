"""Thumbnails: the storyboard at blocking fidelity, drawn by code.

Each panel is rendered from the composition alone: a horizon line for the set,
gray silhouettes sized from each figure's stance, height, and width (the same
geometry the composition solver used), labeled props, and the real device
screens. Free to render, and fast to iterate on.

The same drawing, saved per panel with the lettering zones marked instead of
lettered (`panel_guide_svg`), is the composition guide the per-panel art stage
draws from.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import Panel, Set
from ..models.composition import FigurePlacement, PanelComposition
from ..models.shotlist import Stance
from ..render import text as tx
from ..fonts import REGISTRY
from .geometry import Box, figure
from .scene import Ellipse, Group, Node, Paint, PathNode, Rect, ScenePage

SKY, GROUND, HORIZON = "#f4f5f7", "#e6e8eb", "#b9bec5"
FIGURE, FIGURE_EDGE, LABEL = "#9aa1a9", "#6f7680", "#3b3f45"
RESERVE = "#4c8bf5"


@dataclass(frozen=True)
class Tones:
    """Thumbnail colors; dark looks get a dark stand-in so their panels still read."""

    sky: str = SKY
    ground: str = GROUND
    horizon: str = HORIZON
    figure: str = FIGURE
    edge: str = FIGURE_EDGE
    label: str = LABEL


LIGHT = Tones()
DARK = Tones("#0f1729", "#16213a", "#2f4a6b", "#3d5a80", "#5fa8d3", "#bfe9ff")


@dataclass
class Silhouette:
    character: str
    head: tuple[float, float]  # page px
    hand: tuple[float, float]
    nodes: list[Node]


def _label_font(scale: float) -> tx.Font:
    return tx.Font(REGISTRY.resolve("Work Sans", 700), 15 * scale)


def set_nodes(set_: Set | None, set_id: str, box: Box, scale: float, horizon: float,
              vanish_x: float = 0.5, t: Tones = LIGHT) -> list[Node]:
    """Sky, ground, and a perspective floor converging on the vanishing point."""
    hy = box.y + box.h * horizon
    vx = box.x + box.w * vanish_x
    bottom = box.y + box.h
    nodes: list[Node] = [
        Rect(box.x, box.y, box.w, box.h, Paint(t.sky)),
        Rect(box.x, hy, box.w, max(0.0, bottom - hy), Paint(t.ground)),
    ]
    grid = Paint(stroke=t.horizon, width=1 * scale, opacity=0.7)
    if bottom > hy + 4:
        for i in range(-8, 9):  # rays from the vanishing point to the frame bottom
            x_end = vx + i * box.w * 0.22
            nodes.append(PathNode(f"M{vx:.1f},{hy:.1f} L{x_end:.1f},{bottom:.1f}", grid))
        depth = bottom - hy
        for k in range(1, 6):  # receding floor lines, closer together toward the horizon
            y = hy + depth * (k / 6) ** 2
            nodes.append(PathNode(f"M{box.x:.1f},{y:.1f} H{box.x + box.w:.1f}", grid))
    nodes.append(PathNode(f"M{box.x:.1f},{hy:.1f} H{box.x + box.w:.1f}",
                          Paint(stroke=t.edge, width=2 * scale)))
    f = _label_font(scale * 0.85)
    label = tx.block(set_.name if set_ else set_id, f, box.w * 0.5)
    nodes.append(label.place(box.x + box.w - label.width - 10 * scale, box.y + 8 * scale,
                             t.horizon, align="left"))
    return nodes


def foreground_nodes(text: str, box: Box, scale: float, side: str = "left") -> list[Node]:
    """A dark framing element nearest the camera, cropped by the frame edge."""
    w, h = box.w * 0.22, box.h * 0.75
    x = box.x - w * 0.15 if side == "left" else box.x + box.w - w * 0.85
    y = box.y + box.h - h * 0.9
    f = _label_font(scale * 0.85)
    lab = tx.block(f"FG: {text}", f, w * 1.4)
    return [Rect(x, y, w, h * 1.2, Paint("#5b6168", "#3b3f45", 2 * scale), rx=w * 0.25),
            lab.place(x + w / 2 + (w * 0.1 if side == "left" else -w * 0.1), y + h * 0.4,
                      "#ffffff")]


def silhouette(panel: Panel, f: FigurePlacement, dims: tuple[float, float], box: Box,
               scale: float, name: str, t: Tones = LIGHT) -> Silhouette:
    rel, width = dims
    g = figure(panel.shot, rel, f.x, f.ground, f.scale, f.stance, width)
    X = lambda u: box.x + u * box.w  # noqa: E731
    Y = lambda v: box.y + v * box.h  # noqa: E731
    h_px = g.height * box.h
    w_px = max(g.width * box.h, h_px * 0.25)
    fg = str(f.plane) == "foreground"
    if t is LIGHT:
        body = "#6f7680" if fg else ("#b4b9bf" if str(f.plane) == "background" else FIGURE)
    else:
        body = "#4f6f99" if fg else ("#26385a" if str(f.plane) == "background" else t.figure)
    paint = Paint(body, t.edge, 2 * scale)
    cx = X(g.x)
    if Stance(f.stance) == Stance.LYING:
        r = h_px * 0.42
        body = Rect(cx - w_px / 2, Y(g.ground) - h_px, w_px, h_px, paint, rx=h_px / 2)
        head = (cx + (w_px / 2 - r) * (1 if f.facing != "left" else -1), Y(g.ground) - h_px / 2)
    else:
        r = min(h_px * 0.13, w_px * 0.45)
        head = (cx, Y(g.ground) - h_px + r)
        body = Rect(cx - w_px / 2, head[1] + r * 0.9, w_px, max(h_px - 2 * r, r),
                    paint, rx=min(w_px, h_px) * 0.3)
    nodes: list[Node] = [body, Ellipse(head[0], head[1], r, r, paint)]
    if f.facing in ("left", "right"):  # a nose shows which way they face
        d = 1 if f.facing == "right" else -1
        nodes.append(PathNode(f"M{head[0] + d * r * 0.8:.1f},{head[1] - r * 0.25:.1f} "
                              f"L{head[0] + d * r * 1.35:.1f},{head[1] + r * 0.1:.1f} "
                              f"L{head[0] + d * r * 0.8:.1f},{head[1] + r * 0.35:.1f} Z", paint))
    font = _label_font(scale)
    lab = tx.block(name, font, max(w_px * 1.6, 80 * scale))
    ly = min(Y(g.ground) - lab.height - 4 * scale, box.y + box.h - lab.height - 4 * scale)
    nodes.append(lab.place(cx, ly, "#ffffff", outline=Paint(stroke=t.edge,
                                                            width=3 * scale)))
    nodes.append(lab.place(cx, ly, "#ffffff"))
    hand = (cx, Y(g.ground) - h_px * 0.5)
    return Silhouette(f.character, head, hand, nodes)


def prop_nodes(name: str, box: Box, scale: float) -> list[Node]:
    font = _label_font(scale * 0.9)
    lab = tx.block(name, font, box.w * 1.5)
    return [Rect(box.x, box.y, box.w, box.h, Paint("#ffffff", FIGURE_EDGE, 1.5 * scale,
                                                   dash=f"{6 * scale} {4 * scale}"), rx=6 * scale),
            lab.place(box.cx, box.cy - lab.height / 2, LABEL)]


def annotation(panel: Panel, number: int, box: Box, scale: float) -> list[Node]:
    """Panel number, shot, and angle in the corner — how storyboards are read."""
    angle = "" if panel.angle == "eye-level" else f" · {panel.angle}"
    if panel.tilt_deg:
        angle += f" {panel.tilt_deg:+.0f}°"
    font = _label_font(scale * 0.8)
    t = tx.block(f"{number} · {panel.shot}{angle}", font, box.w)
    return [Rect(box.x, box.y + box.h - t.height - 6 * scale, t.width + 12 * scale,
                 t.height + 6 * scale, Paint("#ffffffcc")),
            t.place(box.x + 6 * scale, box.y + box.h - t.height - 3 * scale, LABEL,
                    align="left")]


def reserve_nodes(plan: PanelComposition, box: Box, scale: float) -> list[Node]:
    """Lettering zones, for the art guide: 'leave this area quiet'."""
    nodes: list[Node] = []
    font = _label_font(scale * 0.8)
    for lp in plan.letters:
        b = lp.box
        r = Box(box.x + b.x * box.w, box.y + b.y * box.h, b.w * box.w, b.h * box.h)
        nodes.append(Rect(r.x, r.y, r.w, r.h, Paint("#4c8bf51a", RESERVE, 1.5 * scale,
                                                     dash=f"{8 * scale} {5 * scale}"),
                          rx=8 * scale))
        lab = tx.block(f"{lp.kind}", font, r.w)
        nodes.append(lab.place(r.cx, r.cy - lab.height / 2, RESERVE))
    return nodes


def guide_page(nodes: list[Node], width: int, height: int, panel_id: str) -> ScenePage:
    return ScenePage(f"guide-{panel_id}", width, height, SKY, Group(nodes, label=panel_id))

