"""Scene → SVG. The reference output; other backends derive from it."""

from __future__ import annotations

import base64
from enum import StrEnum
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from ... import svg as svgutil
from ...fonts import FontFace, metrics
from ...models.direction import (
    Glow, Grain, Halftone, Misregister, Monochrome, Posterize, Wobble,
)
from ..scene import (
    Asset, Ellipse, Group, Node, Overlay, Paint, PathNode, Rect, Scene, ScenePage, Text,
)


class FontMode(StrEnum):
    OUTLINE = "outline"  # glyphs → paths; portable and deterministic (default)
    EMBED = "embed"  # fonts embedded as @font-face; text stays selectable
    SYSTEM = "system"  # font names only; correct only where the fonts are installed


def _n(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _paint(p: Paint) -> str:
    attrs = [f'fill="{p.fill}"']
    if p.stroke:
        attrs += [f'stroke="{p.stroke}"', f'stroke-width="{_n(p.width)}"',
                  f'stroke-linejoin="{p.linejoin}"', 'stroke-linecap="round"']
        if p.dash:
            attrs.append(f'stroke-dasharray="{p.dash}"')
    if p.opacity < 1:
        attrs.append(f'opacity="{_n(p.opacity)}"')
    return " ".join(attrs)


_EFFECT_ORDER = {"wobble": 0, "posterize": 1, "monochrome": 2, "glow": 3, "misregister": 4}


def _face_css_name(face: FontFace) -> str:
    return face.family


class SvgWriter:
    def __init__(self, font_mode: FontMode = FontMode.OUTLINE):
        self.font_mode = font_mode

    def write(self, page: ScenePage, scene: Scene) -> str:
        self._defs: list[str] = []
        self._symbols: dict[str, str] = {}
        self._glyphs: set[str] = set()
        self._effect_ids: dict[str, str] = {}
        self._clip = 0
        self._gid = 0
        body = self._node(page.root)
        head = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'viewBox="0 0 {page.width} {page.height}" width="{page.width}" '
            f'height="{page.height}">',
        ]
        defs = list(self._symbols.values()) + self._defs
        if self.font_mode == FontMode.EMBED:
            defs.insert(0, self._font_faces(scene.fonts))
        out = head + ["<defs>", *defs, "</defs>",
                      f'<rect width="{page.width}" height="{page.height}" '
                      f'fill="{page.background}"/>', body, "</svg>"]
        return "\n".join(out) + "\n"

    # --- nodes -------------------------------------------------------------------
    def _node(self, node: Node) -> str:
        match node:
            case Group():
                return self._group(node)
            case Rect():
                rx = f' rx="{_n(node.rx)}"' if node.rx else ""
                return (f'<rect x="{_n(node.x)}" y="{_n(node.y)}" width="{_n(node.w)}" '
                        f'height="{_n(node.h)}"{rx} {_paint(node.paint)}/>')
            case Ellipse():
                return (f'<ellipse cx="{_n(node.cx)}" cy="{_n(node.cy)}" rx="{_n(node.rx)}" '
                        f'ry="{_n(node.ry)}" {_paint(node.paint)}/>')
            case PathNode():
                return f'<path d="{node.d}" {_paint(node.paint)}/>'
            case Asset():
                return self._asset(node)
            case Text():
                return self._text(node)
            case Overlay():
                return self._overlay(node)
        raise TypeError(f"Unknown scene node {node!r}")

    def _group(self, g: Group) -> str:
        attrs = []
        if g.label:
            attrs.append(f"id={quoteattr(g.label)}")
        if g.transform:
            attrs.append(f'transform="{g.transform}"')
        if g.clip:
            self._clip += 1
            cid = f"clip-{self._clip}"
            c = g.clip
            rx = f' rx="{_n(c.rx)}"' if c.rx else ""
            self._defs.append(f'<clipPath id="{cid}"><rect x="{_n(c.x)}" y="{_n(c.y)}" '
                              f'width="{_n(c.w)}" height="{_n(c.h)}"{rx}/></clipPath>')
            attrs.append(f'clip-path="url(#{cid})"')
        inner = "\n".join(self._node(c) for c in g.children)

        # Filter effects wrap the content, innermost first; misregistration adds an
        # offset, single-ink copy of the content behind it.
        for e in sorted(g.effects, key=lambda e: _EFFECT_ORDER[e.kind]):
            if isinstance(e, Misregister):
                self._gid += 1
                gid = f"plate-{self._gid}"
                fid = self._filter(e)
                inner = (f'<use href="#{gid}" xlink:href="#{gid}" filter="url(#{fid})" '
                         f'opacity="{_n(e.opacity)}" style="mix-blend-mode:multiply"/>\n'
                         f'<g id="{gid}">\n{inner}\n</g>')
            else:
                inner = f'<g filter="url(#{self._filter(e)})">\n{inner}\n</g>'
        return f"<g {' '.join(attrs)}>\n{inner}\n</g>" if attrs else f"<g>\n{inner}\n</g>"

    # --- effects -------------------------------------------------------------------
    def _def_once(self, key: str, make) -> str:
        if key not in self._effect_ids:
            eid = f"fx-{len(self._effect_ids) + 1}"
            self._effect_ids[key] = eid
            self._defs.append(make(eid))
        return self._effect_ids[key]

    def _filter(self, e) -> str:
        key = e.model_dump_json()
        if isinstance(e, Monochrome):
            body = '<feColorMatrix type="saturate" values="0"/>'
        elif isinstance(e, Posterize):
            steps = " ".join(_n(i / (e.levels - 1)) for i in range(e.levels))
            body = ('<feComponentTransfer>'
                    + "".join(f'<feFunc{c} type="discrete" tableValues="{steps}"/>' for c in "RGB")
                    + "</feComponentTransfer>")
        elif isinstance(e, Wobble):
            body = (f'<feTurbulence type="fractalNoise" baseFrequency="{e.frequency}" '
                    f'numOctaves="2" seed="{e.seed}" result="noise"/>'
                    f'<feDisplacementMap in="SourceGraphic" in2="noise" scale="{e.scale_px * 2}" '
                    f'xChannelSelector="R" yChannelSelector="G"/>')
        elif isinstance(e, Glow):
            body = (f'<feGaussianBlur in="SourceGraphic" stdDeviation="{_n(e.radius_px)}" '
                    f'result="blur"/>'
                    f'<feComponentTransfer in="blur" result="bloom"><feFuncA type="linear" '
                    f'slope="{_n(e.strength)}"/></feComponentTransfer>'
                    f'<feMerge><feMergeNode in="bloom"/><feMergeNode in="SourceGraphic"/>'
                    f'</feMerge>')
        elif isinstance(e, Misregister):
            body = (f'<feFlood flood-color="{e.color}"/>'
                    f'<feComposite in2="SourceAlpha" operator="in"/>'
                    f'<feOffset dx="{_n(e.dx_px)}" dy="{_n(e.dy_px)}"/>')
        else:
            raise TypeError(f"Not a filter effect: {e!r}")
        return self._def_once(key, lambda eid: (
            f'<filter id="{eid}" x="-5%" y="-5%" width="110%" height="110%" '
            f'color-interpolation-filters="sRGB">{body}</filter>'))

    def _overlay(self, o: Overlay) -> str:
        e = o.effect
        if isinstance(e, Halftone):
            sp, r = e.spacing_px * o.scale, e.radius_px * o.scale
            pid = self._def_once(e.model_dump_json() + f"@{o.scale}", lambda eid: (
                f'<pattern id="{eid}" patternUnits="userSpaceOnUse" width="{_n(sp)}" '
                f'height="{_n(sp)}" patternTransform="rotate({_n(e.angle_deg)})">'
                f'<circle cx="{_n(sp / 2)}" cy="{_n(sp / 2)}" r="{_n(r)}" fill="{e.color}"/>'
                f'</pattern>'))
            fill = f"url(#{pid})"
            filt = ""
        elif isinstance(e, Grain):
            fid = self._def_once(e.model_dump_json(), lambda eid: (
                f'<filter id="{eid}" x="0" y="0" width="100%" height="100%">'
                f'<feTurbulence type="fractalNoise" baseFrequency="{e.frequency}" numOctaves="3" '
                f'seed="11" stitchTiles="stitch"/><feColorMatrix type="saturate" values="0"/>'
                f'</filter>'))
            fill, filt = "#808080", f' filter="url(#{fid})"'
        else:
            raise TypeError(f"Not an overlay effect: {e!r}")
        return (f'<rect x="{_n(o.x)}" y="{_n(o.y)}" width="{_n(o.w)}" height="{_n(o.h)}" '
                f'fill="{fill}" opacity="{_n(e.opacity)}"{filt} '
                f'style="mix-blend-mode:multiply"/>')

    def _asset(self, a: Asset) -> str:
        if a.ref not in self._symbols:
            self._symbols[a.ref] = svgutil.as_symbol(Path(a.source).read_text("utf-8"), a.ref)
        use = (f'<use href="#{a.ref}" xlink:href="#{a.ref}" x="{_n(a.x)}" y="{_n(a.y)}" '
               f'width="{_n(a.w)}" height="{_n(a.h)}"/>')
        if a.mirror:
            return f'<g transform="translate({_n(2 * a.x + a.w)},0) scale(-1,1)">{use}</g>'
        return use

    def _text(self, t: Text) -> str:
        parts = []
        if t.outline:
            parts.append(self._text_body(t, Paint(fill=t.outline.stroke or "#fff",
                                                  stroke=t.outline.stroke,
                                                  width=t.outline.width)))
        parts.append(self._text_body(t, Paint(fill=t.fill)))
        inner = "\n".join(parts)
        if t.rotate:
            deg, cx, cy = t.rotate
            return f'<g transform="rotate({_n(deg)} {_n(cx)} {_n(cy)})">\n{inner}\n</g>'
        return inner

    def _text_body(self, t: Text, paint: Paint) -> str:
        if self.font_mode == FontMode.OUTLINE:
            return self._outlined(t, paint)
        weight = t.face.weight
        lines = "".join(
            f'<text x="{_n(line.x)}" y="{_n(line.y)}">{escape(line.text)}</text>'
            for line in t.lines)
        return (f'<g font-family={quoteattr(_face_css_name(t.face))} font-weight="{weight}" '
                f'font-size="{_n(t.size)}" {_paint(paint)}>{lines}</g>')

    def _outlined(self, t: Text, paint: Paint) -> str:
        m = metrics(t.face)
        k = t.size / m.upm
        uses = []
        for line in t.lines:
            x = line.x
            for ch in line.text:
                glyph = m.glyph_name(ch)
                gid = f"g-{t.face.key}-{glyph}"
                if gid not in self._glyphs:
                    self._glyphs.add(gid)
                    self._defs.append(f'<path id="{gid}" d="{m.outline(glyph)}"/>')
                if not ch.isspace():
                    uses.append(f'<use href="#{gid}" xlink:href="#{gid}" '
                                f'transform="translate({_n(x)},{_n(line.y)}) '
                                f'scale({k:.5f},{-k:.5f})"/>')
                x += m.advance(ch, t.size)
        # Stroke width is in user space; glyphs are scaled, so compensate.
        if paint.stroke:
            paint = Paint(paint.fill, paint.stroke, paint.width / k, paint.dash)
            body = "\n".join(u.replace("/>", f' {_paint(paint)}/>') for u in uses)
            return f"<g>{body}</g>"
        return f"<g {_paint(paint)}>{''.join(uses)}</g>"

    def _font_faces(self, faces: list[FontFace]) -> str:
        rules = []
        for f in faces:
            data = base64.b64encode(f.path.read_bytes()).decode()
            rules.append(f"@font-face {{ font-family: '{f.family}'; font-weight: {f.weight}; "
                         f"src: url(data:font/ttf;base64,{data}) format('truetype'); }}")
        return "<style>" + "\n".join(rules) + "</style>"


class SvgBackend:
    name = "svg"

    def __init__(self, font_mode: FontMode = FontMode.OUTLINE):
        self.writer = SvgWriter(font_mode)

    def render(self, scene: Scene, out_dir: Path) -> list[Path]:
        paths = []
        for i, page in enumerate(scene.pages, 1):
            p = out_dir / f"page-{i:02d}.svg"
            p.write_text(self.writer.write(page, scene), encoding="utf-8")
            paths.append(p)
        return paths
