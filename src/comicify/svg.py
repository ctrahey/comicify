"""SVG asset conventions, validation, and embedding.

Generated art is frozen into assets/ as standalone SVG documents on fixed
canvases, so every asset can be opened on its own and composed predictably.
Assets contain no text (lettering is the renderer's job, with bundled fonts),
no scripts, and no external references.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", XLINK_NS)


@dataclass(frozen=True)
class Canvas:
    width: int
    height: int
    ground: int | None = None  # y of the ground line, for figures
    figure_height: int | None = None  # standing height of a relative_height=1.0 figure

    @property
    def view_box(self) -> str:
        return f"0 0 {self.width} {self.height}"

    def describe(self) -> str:
        parts = [f'viewBox="{self.view_box}" (width {self.width}, height {self.height})']
        if self.ground is not None:
            parts.append(f"ground line at y={self.ground}; the figure stands on it, "
                         f"horizontally centered at x={self.width // 2}")
        return "; ".join(parts)


# Anchor attributes on a figure's root <svg>: data-head="x,y" (center of the face)
# and data-hand="x,y" (the hand that holds or wears a device). Used to frame
# close-ups and aim balloon tails.
FIGURE_ANCHORS = ("data-head", "data-hand")

CHARACTER_CANVAS = Canvas(600, 600, ground=580, figure_height=540)
SET_CANVAS = Canvas(1600, 900)
PROP_CANVAS = Canvas(400, 400)

FORBIDDEN_TAGS = {"script", "foreignObject", "image", "text", "tspan", "textPath", "style",
                  "iframe", "video", "audio", "animate", "animateTransform", "set"}
MAX_BYTES = 250_000
_URL_RE = re.compile(r"url\(\s*['\"]?([^)'\"]*)")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def anchors(svg: str) -> dict[str, tuple[float, float]]:
    """Read data-* anchor points from an asset's root element."""
    root = ET.fromstring(svg)
    out = {}
    for name in FIGURE_ANCHORS:
        value = root.get(name)
        if value:
            try:
                x, y = (float(v) for v in value.replace(" ", ",").split(",") if v)
                out[name.removeprefix("data-")] = (x, y)
            except ValueError:
                pass
    return out


def validate(svg: str, canvas: Canvas, anchors: tuple[str, ...] = ()) -> list[str]:
    """Problems with a generated SVG asset (empty list = acceptable)."""
    problems: list[str] = []
    if len(svg.encode()) > MAX_BYTES:
        problems.append(f"SVG is {len(svg.encode())} bytes; keep it under {MAX_BYTES}")
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as e:
        return [f"not well-formed XML: {e}"]
    if _local(root.tag) != "svg":
        return ["root element must be <svg>"]
    if " ".join(root.get("viewBox", "").replace(",", " ").split()) != canvas.view_box:
        problems.append(f'root viewBox must be exactly "{canvas.view_box}"')

    for name in anchors:
        value = root.get(name, "")
        try:
            x, y = (float(v) for v in value.replace(" ", ",").split(",") if v)
            if not (0 <= x <= canvas.width and 0 <= y <= canvas.height):
                problems.append(f"{name} point is outside the canvas")
        except ValueError:
            problems.append(f'root <svg> needs {name}="x,y" (canvas coordinates)')

    drawn = 0
    for el in root.iter():
        tag = _local(el.tag)
        if tag in FORBIDDEN_TAGS:
            problems.append(f"<{tag}> is not allowed in assets")
        if tag in {"path", "circle", "ellipse", "rect", "polygon", "polyline", "line"}:
            drawn += 1
        for attr, value in el.attrib.items():
            name = _local(attr)
            if name.startswith("on"):
                problems.append(f"event attribute {name} is not allowed")
            if name == "href" and not value.startswith("#"):
                problems.append(f"external reference {value!r} is not allowed")
            for ref in _URL_RE.findall(value):
                if not ref.startswith("#"):
                    problems.append(f"external url({ref}) is not allowed")
    if drawn < 3:
        problems.append("the drawing is nearly empty; draw the subject with real shapes")
    return sorted(set(problems))


def extract_svg(text: str) -> str:
    """Tolerate code fences or prose around the SVG document."""
    start, end = text.find("<svg"), text.rfind("</svg>")
    return text[start:end + 6] if start != -1 and end != -1 else text


def as_symbol(svg: str, symbol_id: str) -> str:
    """Re-express a standalone SVG document as a <symbol>, namespacing its ids.

    Ids are prefixed with the symbol id so multiple assets can share one document.
    """
    root = ET.fromstring(svg)
    prefix = f"{symbol_id}--"
    ids = {el.get("id") for el in root.iter() if el.get("id")}

    def remap(value: str) -> str:
        def sub(m: re.Match) -> str:
            ref = m.group(1)
            return f"url(#{prefix}{ref[1:]}" if ref.startswith("#") and ref[1:] in ids else m.group(0)
        return _URL_RE.sub(sub, value)

    for el in root.iter():
        for attr, value in list(el.attrib.items()):
            name = _local(attr)
            if name == "id":
                el.set(attr, prefix + value)
            elif name == "href" and value.startswith("#") and value[1:] in ids:
                el.set(attr, "#" + prefix + value[1:])
            elif "url(" in value:
                el.set(attr, remap(value))

    symbol = ET.Element(f"{{{SVG_NS}}}symbol", {"id": symbol_id,
                                                  "viewBox": root.get("viewBox", ""),
                                                  "overflow": "visible"})
    symbol.extend(list(root))
    return ET.tostring(symbol, encoding="unicode")
