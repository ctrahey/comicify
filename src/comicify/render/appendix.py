"""Appendix pages: the comic's own source, as syntax-highlighted listings.

Shows how the tool works: the author's prompt, the clarification session, and
every structured intermediate, in pipeline order, flowing across columns and
pages in a monospace face.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..fonts import REGISTRY, metrics
from ..manifest import Manifest
from ..project import Project
from .scene import Group, Paint, PathNode, Rect, ScenePage, Text, TextLine

# Light, print-friendly highlighting.
COLORS = {
    "text": "#24292f", "key": "#0550ae", "string": "#0a7c45", "number": "#b35900",
    "literal": "#8250df", "comment": "#6e7781", "punct": "#6e7781", "heading": "#cf222e",
    "gutter": "#8c959f",
}

_KEY = re.compile(r"^(\s*)(- )?([A-Za-z0-9_.\-]+)(:)(\s|$)")
_DASH = re.compile(r"^(\s*)(- )")
_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")
_LITERAL = {"true", "false", "null", "~", "|", ">", "|-", ">-"}


Token = tuple[str, str]  # (kind, text)


def yaml_tokens(line: str, in_block: bool) -> list[Token]:
    """Tokenize one YAML line for display (not a parser: good enough to read)."""
    if in_block:
        return [("string", line)]
    if line.lstrip().startswith("#"):
        return [("comment", line)]
    out: list[Token] = []
    rest = line
    if m := _KEY.match(line):
        indent, dash, key, colon, _ = m.groups()
        out += [("text", indent)] + ([("punct", dash)] if dash else [])
        out += [("key", key), ("punct", colon)]
        rest = line[m.end(4):]
    elif m := _DASH.match(line):
        out += [("text", m.group(1)), ("punct", m.group(2))]
        rest = line[m.end():]
    value = rest.strip()
    lead = rest[: len(rest) - len(rest.lstrip())]
    if not value:
        return out + [("text", rest)]
    kind = ("literal" if value in _LITERAL else
            "number" if _NUMBER.match(value) else "string")
    return out + [("text", lead), (kind, value)]


def markdown_tokens(line: str) -> list[Token]:
    if line.startswith("#"):
        return [("heading", line)]
    if line.strip() in ("---",):
        return [("punct", line)]
    return [("text", line)]


@dataclass
class Listing:
    title: str
    subtitle: str
    lines: list[list[Token]]


def listing(project: Project, path: Path, manifest: Manifest) -> Listing:
    rel = project.rel(path)
    text = path.read_text("utf-8").rstrip("\n")
    entry = manifest.entries.get(rel)
    subtitle = (f"{entry.produced_by} · {entry.model}" if entry else
                "author input" if path.suffix == ".md" and "sessions" not in rel else
                "tool-written session notes" if "sessions" in rel else "")
    lines: list[list[Token]] = []
    in_block, block_indent = False, 0
    is_md = path.suffix == ".md"
    for raw in text.splitlines():
        if is_md:
            lines.append(markdown_tokens(raw))
            continue
        indent = len(raw) - len(raw.lstrip())
        if in_block and raw.strip() and indent < block_indent:
            in_block = False
        lines.append(yaml_tokens(raw, in_block))
        if raw.rstrip().endswith(("|", "|-", ">", ">-")):
            in_block, block_indent = True, indent + 1
    return Listing(rel, subtitle, lines)


def appendix_files(project: Project, look: str) -> list[Path]:
    s = project.structured_dir
    order = [project.prompt_path, *project.session_files("clarify"),
             s / "direction" / "narrative.yaml", s / "direction" / "cinematography.yaml",
             s / "brief.yaml", s / "product.yaml", s / "cast.yaml",
             *sorted((s / "characters").glob("*.yaml")), s / "story.yaml",
             *sorted((s / "sets").glob("*.yaml")), s / "props.yaml", s / "shotlist.yaml",
             s / "comic.yaml", s / "looks" / look / "style.yaml"]
    return [p for p in order if p.exists()]


def appendix_pages(project: Project, look: str, width: int, height: int,
                   paper: str, title_face_family: str = "Bangers") -> list[ScenePage]:
    scale = height / 1080
    mono = REGISTRY.resolve("JetBrains Mono", 400)
    mono_bold = REGISTRY.resolve("JetBrains Mono", 700)
    head_face = REGISTRY.resolve(title_face_family, 400)
    m = metrics(mono)
    size = 12.5 * scale
    advance = m.advance("M", size)
    lh = m.line_height(size, 1.25)
    margin, gap = 48 * scale, 36 * scale
    cols = 3
    col_w = (width - 2 * margin - gap * (cols - 1)) / cols
    max_chars = int(col_w / advance)
    top = margin + 64 * scale
    bottom = height - margin

    manifest = Manifest.load(project)
    listings = [listing(project, p, manifest) for p in appendix_files(project, look)]

    pages: list[ScenePage] = []
    group: Group | None = None
    col = cols  # force a new page on first use
    y = top

    def new_page() -> None:
        nonlocal group, col, y
        group = Group(label=f"appendix-{len(pages) + 1}")
        n = len(pages) + 1
        group.add(Text([TextLine(margin, margin + 40 * scale, f"Appendix — the comic's source ({n})")],
                       head_face, 40 * scale, COLORS["text"]))
        group.add(PathNode(f"M{margin},{margin + 54 * scale} H{width - margin}",
                           Paint(stroke=COLORS["gutter"], width=1.2 * scale)))
        pages.append(ScenePage(f"appendix-{n}", width, height, paper, group))
        col, y = 0, top

    def next_column() -> None:
        nonlocal col, y
        col += 1
        y = top
        if col >= cols:
            new_page()

    def x0() -> float:
        return margin + col * (col_w + gap)

    def emit(tokens: list[Token], number: int | None) -> None:
        nonlocal y
        if y + lh > bottom:
            next_column()
        assert group is not None
        base = x0()
        if number is not None:
            group.add(Text([TextLine(base, y + m.ascent(size), f"{number:>3}")], mono, size * 0.85,
                           COLORS["gutter"]))
        cx = base + advance * 4
        for kind, chunk in tokens:
            if chunk:
                group.add(Text([TextLine(cx, y + m.ascent(size), chunk)], mono, size,
                               COLORS.get(kind, COLORS["text"])))
                cx += advance * len(chunk)
        y += lh

    new_page()
    for lst in listings:
        if y + lh * 4 > bottom:  # don't strand a header at the bottom of a column
            next_column()
        assert group is not None
        group.add(Rect(x0() - 6 * scale, y, col_w + 12 * scale, lh * 2.2,
                       Paint("#eef1f5"), rx=4 * scale))
        group.add(Text([TextLine(x0(), y + m.ascent(size) + 2 * scale, lst.title)], mono_bold, size,
                       COLORS["text"]))
        group.add(Text([TextLine(x0(), y + lh + m.ascent(size * 0.85) + 2 * scale, lst.subtitle)],
                       mono, size * 0.85, COLORS["gutter"]))
        y += lh * 2.6
        width_chars = max_chars - 4
        for i, tokens in enumerate(lst.lines, 1):
            # Hard-wrap long lines, continuing with the same token kinds.
            line_len = sum(len(t) for _, t in tokens)
            if line_len <= width_chars:
                emit(tokens, i)
                continue
            chunk: list[Token] = []
            used, first = 0, True
            for kind, text in tokens:
                while text:
                    room = width_chars - used
                    piece, text = text[:room], text[room:]
                    chunk.append((kind, piece))
                    used += len(piece)
                    if used >= width_chars:
                        emit(chunk, i if first else None)
                        first, chunk, used = False, [("punct", "  ↪ ")], 4
            if chunk and used > 4 or first:
                emit(chunk, i if first else None)
        y += lh
    return pages
