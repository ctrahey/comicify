"""Deterministic text layout using the bundled fonts' own metrics."""

from __future__ import annotations

from dataclasses import dataclass

from ..fonts import REGISTRY, FontFace, metrics
from ..models.direction import FontChoice
from .scene import Text, TextLine


_FALLBACKS = {"→": "->", "←": "<-", "—": "-", "–": "-", "…": "...", "‘": "'", "’": "'",
              "“": '"', "”": '"', "•": "*", "×": "x", "≥": ">=", "≤": "<="}


@dataclass(frozen=True)
class Font:
    face: FontFace
    size: float
    uppercase: bool = False

    @classmethod
    def from_choice(cls, choice: FontChoice, scale: float = 1.0) -> Font:
        return cls(REGISTRY.resolve(choice.family, choice.weight), choice.size * scale,
                   choice.uppercase)

    def scaled(self, factor: float) -> Font:
        return Font(self.face, self.size * factor, self.uppercase)

    def prepare(self, text: str) -> str:
        """Apply case, and substitute characters the face can't draw."""
        text = text.upper() if self.uppercase else text
        m = metrics(self.face)
        if all(m.has_glyph(c) or c in "\n\t" for c in text):
            return text
        return "".join(c if m.has_glyph(c) or c in "\n\t" else _FALLBACKS.get(c, "?")
                       for c in text)

    def width(self, text: str) -> float:
        return metrics(self.face).width(text, self.size)

    @property
    def ascent(self) -> float:
        return metrics(self.face).ascent(self.size)

    @property
    def line_height(self) -> float:
        return metrics(self.face).line_height(self.size)


def wrap(text: str, font: Font, max_width: float) -> list[str]:
    """Greedy word wrap. Words longer than the line are left to overflow."""
    lines: list[str] = []
    for para in font.prepare(text).split("\n"):
        line = ""
        for word in para.split():
            candidate = f"{line} {word}" if line else word
            if line and font.width(candidate) > max_width:
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.append(line)
    return lines


@dataclass(frozen=True)
class Block:
    font: Font
    lines: list[str]
    width: float
    height: float

    def place(self, cx: float, top: float, fill: str, align: str = "center", **kw) -> Text:
        out = []
        for i, line in enumerate(self.lines):
            w = self.font.width(line)
            x = cx - w / 2 if align == "center" else cx
            out.append(TextLine(x, top + self.font.ascent + i * self.font.line_height, line))
        return Text(out, self.font.face, self.font.size, fill, **kw)


def block(text: str, font: Font, max_width: float) -> Block:
    lines = wrap(text, font, max_width)
    width = max((font.width(line) for line in lines), default=0.0)
    return Block(font, lines, width, len(lines) * font.line_height)


def fit(text: str, font: Font, max_width: float, max_height: float,
        min_scale: float = 0.55) -> Block:
    """Largest block (down to min_scale) whose lines fit the box."""
    scale = 1.0
    while True:
        b = block(text, font.scaled(scale), max_width)
        if (b.height <= max_height and b.width <= max_width) or scale <= min_scale:
            return b
        scale = round(scale - 0.05, 2)


# --- rich text: emphasized words ------------------------------------------------------


@dataclass(frozen=True)
class Run:
    text: str
    font: Font


def _norm(word: str) -> str:
    return "".join(c for c in word.lower() if c.isalnum() or c in "'-")


@dataclass(frozen=True)
class RichBlock:
    lines: list[list[Run]]
    font: Font
    width: float
    height: float

    @staticmethod
    def line_width(line: list[Run]) -> float:
        return sum(r.font.width(r.text) for r in line)

    def place(self, cx: float, top: float, fill: str, align: str = "center",
              **kw) -> list[Text]:
        out: list[Text] = []
        for i, line in enumerate(self.lines):
            w = self.line_width(line)
            x = cx - w / 2 if align == "center" else cx
            y = top + self.font.ascent + i * self.font.line_height
            for run in line:
                if run.text.strip():
                    out.append(Text([TextLine(x, y, run.text)], run.font.face, run.font.size,
                                    fill, **kw))
                x += run.font.width(run.text)
        return out


def rich(text: str, font: Font, bold: Font, emphasis: list[str], max_width: float) -> RichBlock:
    """Word-wrap with emphasized words set in the bold face."""
    stress = {_norm(w) for phrase in emphasis for w in phrase.split()}
    lines: list[list[Run]] = []
    for para in font.prepare(text).split("\n"):
        line: list[Run] = []
        width = 0.0
        for word in para.split():
            f = bold if _norm(word) in stress else font
            run = Run(word, f)
            space = Run(" ", font) if line else None
            add = f.width(word) + (font.width(" ") if space else 0)
            if line and width + add > max_width:
                lines.append(line)
                line, width = [run], f.width(word)
            else:
                if space:
                    line.append(space)
                line.append(run)
                width += add
        lines.append(line)
    width = max((RichBlock.line_width(ln) for ln in lines), default=0.0)
    return RichBlock(lines, font, width, len(lines) * font.line_height)


def rich_fit(text: str, font: Font, bold: Font, emphasis: list[str], max_width: float,
             max_height: float, min_scale: float = 0.5) -> RichBlock:
    scale = 1.0
    while True:
        b = rich(text, font.scaled(scale), bold.scaled(scale), emphasis, max_width)
        if (b.height <= max_height and b.width <= max_width) or scale <= min_scale:
            return b
        scale = round(scale - 0.04, 2)
