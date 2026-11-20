"""The letterer: draws the composition's planned lettering in the look's style.

Placement is decided by the composition (structured/composition.yaml); this
module only *draws*, following the art pack's lettering system: balloon shape
and tail style, caption treatment, emphasis, and sound-effect styling (fill,
outline, halo, drop shadow, rotation limits). Text is refit into each planned
box with the look's own fonts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..models.composition import LetterPlacement
from ..models.direction import BalloonShape, CaptionStyle, TailStyle
from ..models.shotlist import TextElement, TextKind
from ..models.style import TextRole
from . import text as tx
from .geometry import Box
from .scene import Ellipse, Group, Node, Paint, PathNode, Rect
from .theme import Theme

SPEECH = {TextKind.SPEECH, TextKind.THOUGHT, TextKind.WHISPER, TextKind.SHOUT}


@dataclass(frozen=True)
class Point:
    x: float
    y: float


@dataclass
class Layers:
    """Strokes under fills (seamless tails), then text."""

    strokes: list[Node] = field(default_factory=list)
    fills: list[Node] = field(default_factory=list)
    texts: list[Node] = field(default_factory=list)

    def nodes(self, label: str, shape_effects: list | None = None) -> list[Node]:
        """Balloon shapes share the art's hand-drawn effects; text stays crisp."""
        shapes = Group([Group(self.strokes, label=f"{label}-strokes"),
                        Group(self.fills, label=f"{label}-fills")],
                       label=f"{label}-shapes", effects=list(shape_effects or []))
        return [shapes, Group(self.texts, label=f"{label}-text")]


@dataclass
class Letterer:
    theme: Theme
    scale: float

    @property
    def lettering(self):
        return self.theme.art.lettering

    def _bold(self, font: tx.Font) -> tx.Font:
        from ..fonts import REGISTRY
        try:
            face = REGISTRY.resolve(font.face.family, self.lettering.emphasis_weight)
        except KeyError:
            face = font.face
        return tx.Font(face, font.size, font.uppercase)

    # --- entry point -------------------------------------------------------------------
    def draw(self, letter: LetterPlacement, el: TextElement, box: Box, target: Point | None,
             chained: Box | None, out: Layers) -> None:
        if letter.kind == TextKind.CAPTION:
            self._caption(el, box, out)
        elif letter.kind == TextKind.SFX:
            self._sfx(el, letter, box, out)
        elif letter.kind == TextKind.DEVICE:
            self._device(el, box, target, out)
        else:
            self._balloon(el, letter, box, target, chained, out)

    # --- balloons ----------------------------------------------------------------------
    def _balloon(self, el: TextElement, letter: LetterPlacement, box: Box,
                 target: Point | None, chained: Box | None, out: Layers) -> None:
        th, lt = self.theme, self.lettering
        ink, fill = th.ink, th.balloon_fill
        width = max(lt.stroke_px * self.scale, 0.01)
        shape = BalloonShape(lt.balloon)
        kind = TextKind(el.kind)
        if kind == TextKind.SHOUT:
            shape_kind = "burst"
        elif kind == TextKind.THOUGHT:
            shape_kind = "cloud"
        else:
            shape_kind = shape.value
        dash = f"{8 * self.scale} {6 * self.scale}" if kind == TextKind.WHISPER else None
        stroke = Paint(fill, ink, width, dash=dash)
        cx, cy = box.cx, box.cy

        # Text area inside the shape.
        inner = {"ellipse": (0.72, 0.7), "cloud": (0.68, 0.64), "burst": (0.64, 0.6)}.get(
            shape_kind, (1.0, 1.0))
        font = th.font(TextRole.DIALOGUE, self.scale * (1.15 if kind == TextKind.SHOUT else 1))
        pad = font.size * lt.padding_em
        max_w = box.w * inner[0] - (0 if inner[0] < 1 else 2 * pad)
        max_h = box.h * inner[1] - (0 if inner[1] < 1 else 2 * pad)
        block = tx.rich_fit(el.text, font, self._bold(font), el.emphasis, max_w, max_h)

        if shape_kind == "none":
            if target:
                start = _edge_point(box, target, "rect")
                end = (target.x + (start[0] - target.x) * 0.2, target.y - 8 * self.scale)
                out.strokes.append(PathNode(f"M{start[0]:.1f},{start[1]:.1f} "
                                            f"L{end[0]:.1f},{end[1]:.1f}",
                                            Paint(stroke=ink, width=width)))
            out.texts += block.place(cx, cy - block.height / 2, ink)
            return

        if shape_kind == "burst":
            d = _burst(cx, cy, box.w / 2, box.h / 2)
            out.strokes.append(PathNode(d, stroke))
            out.fills.append(PathNode(d, Paint(fill)))
        elif shape_kind in ("ellipse", "cloud"):
            out.strokes.append(Ellipse(cx, cy, box.w / 2, box.h / 2, stroke))
            out.fills.append(Ellipse(cx, cy, box.w / 2, box.h / 2, Paint(fill)))
        else:
            r = min(box.w, box.h) * (0.32 if shape_kind == "rounded" else 0.04)
            out.strokes.append(Rect(box.x, box.y, box.w, box.h, stroke, rx=r))
            out.fills.append(Rect(box.x, box.y, box.w, box.h, Paint(fill), rx=r))

        if chained is not None:  # a connector instead of a second tail
            d = _connector(chained, box, font.size * 0.55)
            out.strokes.append(PathNode(d, Paint(fill, ink, width)))
            out.fills.append(PathNode(d, Paint(fill)))
        elif target and kind == TextKind.THOUGHT:
            for i, f in enumerate((0.38, 0.62)):
                bx = cx + (target.x - cx) * f
                by = box.y + box.h + (target.y - box.y - box.h) * f
                r = (12 - i * 4) * self.scale
                out.strokes.append(Ellipse(bx, by, r, r, Paint(fill, ink, width)))
        elif target:
            edge = "ellipse" if shape_kind in ("ellipse", "cloud", "burst") else "rect"
            tail = _tail(box, target, font.size, TailStyle(lt.tail), edge)
            if TailStyle(lt.tail) == TailStyle.LINE:
                out.strokes.append(PathNode(tail, Paint(stroke=ink, width=width)))
            else:
                out.strokes.append(PathNode(tail, stroke))
                out.fills.append(PathNode(tail, Paint(fill)))
        out.texts += block.place(cx, cy - block.height / 2, ink)

    # --- captions ----------------------------------------------------------------------
    def _caption(self, el: TextElement, box: Box, out: Layers) -> None:
        th, lt = self.theme, self.lettering
        style = CaptionStyle(lt.caption_style)
        font = th.font(TextRole.CAPTION, self.scale)
        pad = font.size * 0.45
        block = tx.rich_fit(el.text, font, self._bold(font), el.emphasis, box.w - 2 * pad,
                            box.h - 2 * pad)
        color = th.ink
        if style == CaptionStyle.BOX:
            out.fills.append(Rect(box.x, box.y, box.w, box.h,
                                  Paint(th.caption_fill, th.ink, max(lt.stroke_px * 0.8, 1)
                                        * self.scale)))
        elif style == CaptionStyle.BAR:
            out.fills.append(Rect(box.x, box.y, box.w, box.h, Paint(th.ink)))
            color = th.paper
        out.texts += block.place(box.x + pad, box.y + (box.h - block.height) / 2, color,
                                 align="left")

    # --- device text -------------------------------------------------------------------
    def _device(self, el: TextElement, box: Box, target: Point | None, out: Layers) -> None:
        th = self.theme
        font = th.font(TextRole.DEVICE, self.scale)
        pad = font.size * 0.5
        block = tx.rich_fit(el.text, font, self._bold(font), el.emphasis, box.w - 2 * pad,
                            box.h - 2 * pad)
        r = min(box.h * 0.35, 18 * self.scale)
        stroke = Paint(th.device_bg, th.device_accent, 3 * self.scale)
        if target:
            d = _tail(box, target, font.size * 0.6, TailStyle.STRAIGHT, "rect", reach=0.45)
            out.strokes.append(PathNode(d, stroke))
            out.fills.append(PathNode(d, Paint(th.device_bg)))
        out.strokes.append(Rect(box.x, box.y, box.w, box.h, stroke, rx=r))
        out.fills.append(Rect(box.x, box.y, box.w, box.h, Paint(th.device_bg), rx=r))
        out.texts += block.place(box.cx, box.cy - block.height / 2, th.device_text)

    # --- sound effects -----------------------------------------------------------------
    def _sfx(self, el: TextElement, letter: LetterPlacement, box: Box, out: Layers) -> None:
        th, sty = self.theme, self.lettering.sfx_style
        font = th.font(TextRole.SFX, self.scale * letter.size * sty.scale)
        block = tx.fit(el.text, font, box.w * 1.05, box.h * 1.1, min_scale=0.4)
        fill = (th.color("sfx", th.art.color.anchors[0] if th.art.color.anchors else
                         th.device_alert) if sty.fill == "accent"
                else th.ink if sty.fill == "ink" else sty.fill)
        limit = sty.max_rotation_deg
        rot = max(-limit, min(limit, letter.rotation_deg))
        cx, top = box.cx, box.cy - block.height / 2
        rotate = (rot, cx, box.cy) if rot else None
        size = block.font.size / 64  # effect widths scale with the lettering
        if sty.shadow and sty.shadow_px:
            off = sty.shadow_px * self.scale * size * 1.6
            out.texts.append(block.place(cx + off, top + off, sty.shadow,
                                         outline=Paint(stroke=sty.shadow, width=(
                                             sty.halo_px if sty.halo else sty.outline_px)
                                             * self.scale * size), rotate=rotate))
        if sty.halo and sty.halo_px:
            out.texts.append(block.place(cx, top, sty.halo, outline=Paint(
                stroke=sty.halo, width=sty.halo_px * self.scale * size * 1.6), rotate=rotate))
        outline = (Paint(stroke=sty.outline, width=sty.outline_px * self.scale * size * 1.6)
                   if sty.outline and sty.outline_px else None)
        out.texts.append(block.place(cx, top, fill, outline=outline, rotate=rotate))


# --- geometry helpers -------------------------------------------------------------------


def _edge_point(box: Box, to: Point, edge: str) -> tuple[float, float]:
    cx, cy = box.cx, box.cy
    dx, dy = to.x - cx, to.y - cy
    if edge == "ellipse":
        a = math.atan2(dy / (box.h / 2), dx / (box.w / 2))
        return cx + box.w / 2 * math.cos(a), cy + box.h / 2 * math.sin(a)
    t = min(box.w / 2 / abs(dx) if dx else math.inf, box.h / 2 / abs(dy) if dy else math.inf)
    return cx + dx * t, cy + dy * t


def _tail(box: Box, to: Point, font_size: float, style: TailStyle, edge: str,
          reach: float = 1.0) -> str:
    """A wedge from the balloon's edge toward the speaker, stopping short of the mouth."""
    cx, cy = box.cx, box.cy
    ex, ey = _edge_point(box, to, edge)
    dist = math.hypot(to.x - ex, to.y - ey)
    ux, uy = (to.x - ex) / (dist or 1), (to.y - ey) / (dist or 1)
    length = max(font_size * 0.8, min(dist - font_size * 0.9, font_size * 4.2)) * reach
    tip = (ex + ux * length, ey + uy * length)
    if style == TailStyle.LINE:
        return f"M{ex:.1f},{ey:.1f} L{tip[0]:.1f},{tip[1]:.1f}"
    # Base: two points on the edge, either side of the exit point.
    half = font_size * 0.55
    px, py = -uy, ux
    inset = font_size * 0.35  # start inside the shape so fills overlap seamlessly
    b1 = (ex - ux * inset + px * half, ey - uy * inset + py * half)
    b2 = (ex - ux * inset - px * half, ey - uy * inset - py * half)
    if style == TailStyle.STRAIGHT:
        return (f"M{b1[0]:.1f},{b1[1]:.1f} L{tip[0]:.1f},{tip[1]:.1f} "
                f"L{b2[0]:.1f},{b2[1]:.1f} Z")
    # Curved wedge: bowed toward the side of the balloon's center (classic letterer's tail).
    bow = 0.18 * length
    c1 = ((b1[0] + tip[0]) / 2 + px * bow, (b1[1] + tip[1]) / 2 + py * bow)
    c2 = ((b2[0] + tip[0]) / 2 + px * bow * 0.4, (b2[1] + tip[1]) / 2 + py * bow * 0.4)
    _ = (cx, cy)
    return (f"M{b1[0]:.1f},{b1[1]:.1f} Q{c1[0]:.1f},{c1[1]:.1f} {tip[0]:.1f},{tip[1]:.1f} "
            f"Q{c2[0]:.1f},{c2[1]:.1f} {b2[0]:.1f},{b2[1]:.1f} Z")


def _connector(a: Box, b: Box, half: float) -> str:
    """A short band joining two balloons from the same speaker."""
    ax, ay, bx, by = a.cx, a.cy, b.cx, b.cy
    d = math.hypot(bx - ax, by - ay) or 1
    px, py = -(by - ay) / d * half, (bx - ax) / d * half
    return (f"M{ax + px:.1f},{ay + py:.1f} L{bx + px:.1f},{by + py:.1f} "
            f"L{bx - px:.1f},{by - py:.1f} L{ax - px:.1f},{ay - py:.1f} Z")


def _burst(cx: float, cy: float, rx: float, ry: float, points: int = 22) -> str:
    pts = []
    for i in range(points * 2):
        a = math.pi * i / points
        k = 1.0 if i % 2 == 0 else 0.82
        pts.append(f"{cx + rx * k * math.cos(a):.1f},{cy + ry * k * math.sin(a):.1f}")
    return "M" + " L".join(pts) + " Z"
