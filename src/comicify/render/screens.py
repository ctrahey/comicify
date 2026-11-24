"""Deterministic rendering of subject-product screens.

Screens are never generated art: they're drawn from product.yaml's abstract
screen elements, in a simple flat UI style, so they stay legible, consistent,
and editable as data (Cheng: keep interfaces vague, in the comic's style).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from ..models.product import Screen, ScreenElement, ScreenElementKind
from ..models.style import TextRole
from . import text as tx
from .scene import Ellipse, Group, Node, Paint, PathNode, Rect
from .theme import Theme

K = ScreenElementKind


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    w: float
    h: float


def device_frame(device: str, area: Box, theme: Theme) -> tuple[list[Node], Box]:
    """Draw a device body fitted into `area`; return (nodes, screen box)."""
    ink = theme.ink
    body = "#2a2c34"
    d = device.lower()
    if "watch" in d:
        s = min(area.w, area.h) * 0.82
        x, y = area.x + (area.w - s) / 2, area.y + (area.h - s) / 2
        strap_w = s * 0.56
        sx = x + (s - strap_w) / 2
        nodes: list[Node] = [
            Rect(sx, area.y - 10, strap_w, area.h + 20, Paint("#4a4d57", ink, 3)),
            Rect(x, y, s, s, Paint(body, ink, 4), rx=s * 0.24),
            Rect(x + s, y + s * 0.3, s * 0.05, s * 0.16, Paint(body, ink, 3), rx=4),  # crown
        ]
        inset = s * 0.08
        return nodes, Box(x + inset, y + inset, s - 2 * inset, s - 2 * inset)
    if "phone" in d:
        h = min(area.h * 0.94, area.w * 0.94 / 0.5)
        w = h * 0.5
        x, y = area.x + (area.w - w) / 2, area.y + (area.h - h) / 2
        inset = w * 0.06
        return [Rect(x, y, w, h, Paint(body, ink, 4), rx=w * 0.14)], Box(
            x + inset, y + inset * 1.6, w - 2 * inset, h - inset * 3.2)
    w = min(area.w * 0.92, area.h * 0.92 * 1.5)
    h = w / 1.5
    x, y = area.x + (area.w - w) / 2, area.y + (area.h - h) / 2
    inset = w * 0.04
    return [Rect(x, y, w, h, Paint(body, ink, 4), rx=w * 0.06)], Box(
        x + inset, y + inset, w - 2 * inset, h - 2 * inset)


_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def _fraction(el: ScreenElement) -> float:
    m = _PCT.search(f"{el.content or ''} {el.label or ''}")
    return max(0.0, min(1.0, float(m.group(1)) / 100)) if m else 0.65


@dataclass
class _Row:
    height: float
    draw: Callable[[float], list[Node]]  # y → nodes


def screen_nodes(screen: Screen, box: Box, theme: Theme) -> Group:
    """Lay out a screen's elements top to bottom, shrinking type until they fit."""
    g = Group(label=f"screen-{screen.id}")
    radius = min(box.w, box.h) * 0.16
    g.add(Rect(box.x, box.y, box.w, box.h, Paint(theme.device_bg), rx=radius))

    pad = min(box.w, box.h) * 0.09
    inner = Box(box.x + pad, box.y + pad, box.w - 2 * pad, box.h - 2 * pad)
    base = theme.font(TextRole.DEVICE)

    groups: list[list[ScreenElement]] = []
    for el in screen.elements:  # consecutive buttons share a row
        if el.kind == K.BUTTON and groups and groups[-1][-1].kind == K.BUTTON:
            groups[-1].append(el)
        else:
            groups.append([el])
    for scale in (1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.42, 0.35):
        # Device type scales with the screen, but never below legibility.
        font = base.scaled(max(scale * inner.h / 300, 12 / base.size))
        rows = [_button_row(g, inner, font, theme) if len(g) > 1 else _row(g[0], inner, font, theme)
                for g in groups]
        gap = font.size * 0.45
        total = sum(r.height for r in rows) + gap * max(0, len(rows) - 1)
        if total <= inner.h:
            break

    y = inner.y + max(0.0, (inner.h - total) / 2)
    for r in rows:
        g.add(*r.draw(y))
        y += r.height + gap
    g.clip = Rect(box.x, box.y, box.w, box.h, Paint(), rx=radius)
    return g


TONES = {"positive": "#2e9e5b", "negative": "#d64541"}


def _tone(el: ScreenElement, theme: Theme) -> str:
    if el.tone in TONES:
        return TONES[el.tone]
    return theme.device_alert if el.emphasis else theme.device_accent


def _button_row(els: list[ScreenElement], box: Box, font: tx.Font, theme: Theme) -> _Row:
    gap = font.size * 0.5
    w = (box.w - gap * (len(els) - 1)) / len(els)
    blocks = [tx.fit(" ".join(filter(None, [e.label, e.content])) or "OK", font, w * 0.82,
                     font.line_height * 1.05, min_scale=0.45)
              for e in els]
    h = max(b.height for b in blocks) + font.size * 0.7

    def row(y: float) -> list[Node]:
        out: list[Node] = []
        for i, (e, b) in enumerate(zip(els, blocks)):
            x = box.x + i * (w + gap)
            out += [Rect(x, y, w, h, Paint(_tone(e, theme)), rx=h / 2),
                    b.place(x + w / 2, y + (h - b.height) / 2, "#ffffff")]
        return out
    return _Row(h, row)


def _row(el: ScreenElement, box: Box, font: tx.Font, theme: Theme) -> _Row:
    fg, accent, alert = theme.device_text, theme.device_accent, theme.device_alert
    cx = box.x + box.w / 2
    label = " ".join(filter(None, [el.label, el.content])) or el.kind
    color = alert if el.emphasis else fg

    if el.kind == K.HEADLINE:
        b = tx.block(label, font.scaled(1.35), box.w)
        return _Row(b.height, lambda y: [b.place(cx, y, accent if el.emphasis else fg)])

    if el.kind == K.GAUGE:
        lb = tx.block(el.label or "", font.scaled(0.85), box.w)
        bar_h = font.size * 0.7
        frac = _fraction(el)

        def gauge(y: float) -> list[Node]:
            by = y + lb.height + font.size * 0.2
            return [lb.place(box.x, y, fg, align="left"),
                    Rect(box.x, by, box.w, bar_h, Paint("#ffffff22", fg, 1.5), rx=bar_h / 2),
                    Rect(box.x, by, max(bar_h, box.w * frac), bar_h,
                         Paint(alert if el.emphasis else accent), rx=bar_h / 2)]
        return _Row(lb.height + font.size * 0.2 + bar_h, gauge)

    if el.kind == K.BUTTON:
        b = tx.block(label, font, box.w * 0.8)
        h = b.height + font.size * 0.7

        def button(y: float) -> list[Node]:
            return [Rect(box.x + box.w * 0.08, y, box.w * 0.84, h,
                         Paint(_tone(el, theme)), rx=h / 2),
                    b.place(cx, y + font.size * 0.35, theme.device_bg)]
        return _Row(h, button)

    if el.kind == K.NOTIFICATION:
        pad = font.size * 0.45
        title = tx.block(el.label or "Notification", font.scaled(0.8), box.w - 2 * pad)
        body = tx.block(el.content or "", font, box.w - 2 * pad)
        h = title.height + body.height + 2 * pad

        def card(y: float) -> list[Node]:
            return [Rect(box.x, y, box.w, h, Paint("#ffffff", alert if el.emphasis else accent,
                                                   3), rx=pad * 1.4),
                    title.place(box.x + pad, y + pad, "#6b7080", align="left"),
                    body.place(box.x + pad, y + pad + title.height, "#1b1b1f", align="left")]
        return _Row(h, card)

    if el.kind == K.ICON:
        d = font.size * 1.6
        b = tx.block(label, font, box.w - d * 1.4)

        def icon(y: float) -> list[Node]:
            h = max(d, b.height)
            return [Ellipse(box.x + d / 2, y + h / 2, d / 2, d / 2, Paint(accent)),
                    b.place(box.x + d * 1.3, y + (h - b.height) / 2, color, align="left")]
        return _Row(max(d, b.height), icon)

    if el.kind == K.LIST:
        items = [s.strip() for s in (el.content or label).split(",") if s.strip()]
        blocks = [tx.block(f"• {s}", font.scaled(0.9), box.w) for s in items]

        def lst(y: float) -> list[Node]:
            out = []
            for b in blocks:
                out.append(b.place(box.x, y, fg, align="left"))
                y += b.height
            return out
        return _Row(sum(b.height for b in blocks), lst)

    if el.kind in (K.CHART, K.MAP, K.IMAGE):
        h = box.h * 0.3

        def figure(y: float) -> list[Node]:
            nodes: list[Node] = [Rect(box.x, y, box.w, h, Paint("#ffffff14", fg, 1.5), rx=8)]
            if el.kind == K.CHART:
                for i, f in enumerate((0.4, 0.7, 0.55, 0.9)):
                    bw = box.w / 9
                    nodes.append(Rect(box.x + bw * (1 + 2 * i), y + h * (1 - f * 0.85), bw,
                                      h * f * 0.85 - 4, Paint(accent)))
            elif el.kind == K.MAP:
                nodes.append(PathNode(f"M{box.x + 10},{y + h * 0.7} C{cx},{y} {cx},{y + h} "
                                      f"{box.x + box.w - 10},{y + h * 0.3}",
                                      Paint(stroke=accent, width=4, dash="10 8")))
            return nodes
        return _Row(h, figure)

    # TEXT and anything else
    b = tx.block(label, font, box.w)
    return _Row(b.height, lambda y: [b.place(cx, y, color)])
