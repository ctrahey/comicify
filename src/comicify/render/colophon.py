"""The colophon ("bumper") page: how this comic was made, and what it cost."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from ..fonts import REGISTRY, FontFace
from ..manifest import Manifest
from ..project import Project
from ..usage import Usage, cost_usd, ledger
from . import text as tx
from .scene import Group, Paint, PathNode, Rect, ScenePage
from .theme import Theme


@dataclass
class StageRow:
    stage: str
    models: list[str]
    artifacts: int
    usage: Usage | None  # None when produced before usage was recorded
    cost: float | None = 0.0  # USD; None if any part couldn't be priced


@dataclass
class ColophonData:
    title: str
    logline: str
    rendered_at: str
    renderer_version: int
    pages: int
    panels: int
    layers: list[tuple[str, str]] = field(default_factory=list)  # (axis, name)
    stages: list[StageRow] = field(default_factory=list)
    spent: Usage = field(default_factory=Usage)
    spent_calls: int = 0
    spent_cost: float | None = None
    fonts: list[FontFace] = field(default_factory=list)

    @property
    def total(self) -> Usage:
        return sum((r.usage for r in self.stages if r.usage), Usage())

    @property
    def total_cost(self) -> float | None:
        costs = [r.cost for r in self.stages if r.models != ["code"]]
        return None if any(c is None for c in costs) else sum(costs)

    @property
    def complete(self) -> bool:
        return all(r.usage is not None for r in self.stages if r.models != ["code"])


def _in_comic(rel: str, look: str) -> bool:
    """Storyboard files, plus this look's art: other looks are not part of this comic."""
    for prefix in ("assets/", "structured/looks/"):
        if rel.startswith(prefix):
            return rel[len(prefix):].split("/", 1)[0] == look
    return True


def gather(project: Project, *, look: str, title: str, logline: str, pages: int, panels: int,
           renderer_version: int, fonts: list[FontFace],
           layers: list[tuple[str, str]] | None = None) -> ColophonData:
    manifest = Manifest.load(project)
    rows: dict[str, StageRow] = {}
    for rel, entry in manifest.entries.items():
        if not (project.root / rel).exists() or not _in_comic(rel, look):
            continue
        stage = entry.produced_by.split("@")[0]
        row = rows.setdefault(stage, StageRow(stage, [], 0, Usage()))
        row.artifacts += 1
        if entry.model not in row.models:
            row.models.append(entry.model)
        if entry.usage is None and entry.model != "code":
            row.usage, row.cost = None, None
        elif row.usage is not None and entry.usage is not None:
            row.usage = row.usage + entry.usage
            c = cost_usd(entry.model, entry.usage)
            row.cost = None if (c is None or row.cost is None) else row.cost + c

    calls = ledger(project)
    spent = sum((e.spent for e in calls), Usage())
    costs = [cost_usd(e.model, e.spent) for e in calls if not e.cached]
    # Rank by output tokens: output dominates cost and time. Code stages last.
    ranked = sorted(rows.values(), key=lambda r: (r.usage is None or r.models == ["code"],
                                                  -(r.usage.output_tokens if r.usage else 0)))
    return ColophonData(
        title=title, logline=logline,
        rendered_at=dt.datetime.now().strftime("%Y-%m-%d"),
        renderer_version=renderer_version, pages=pages, panels=panels,
        layers=layers or [],
        stages=ranked,
        spent=spent, spent_calls=sum(1 for e in calls if not e.cached), fonts=fonts,
        spent_cost=None if any(c is None for c in costs) else sum(costs),
    )


def _usd(v: float | None) -> str:
    if v is None:
        return "—"
    return f"${v:,.2f}" if v >= 0.01 else "<$0.01"


def _k(n: int) -> str:
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def colophon_page(data: ColophonData, theme: Theme, width: int, height: int,
                  page_id: str) -> ScenePage:
    s = height / 1080
    ink = theme.ink
    muted = "#6b6f7a"
    margin = 80 * s
    root = Group(label=page_id)

    # House typography, not the look's: this page documents the comic.
    title_font = tx.Font(REGISTRY.resolve("Bangers", 400), 64 * s)
    body = tx.Font(REGISTRY.resolve("Comic Neue", 700), 21 * s)
    small = body.scaled(0.8)
    y = margin

    head = tx.block("Behind the panels", title_font, width - 2 * margin)
    root.add(head.place(margin, y, ink, align="left"))
    y += head.height + 10 * s
    sub = tx.block(f"{data.title} — {data.logline}", body, width - 2 * margin)
    root.add(sub.place(margin, y, muted, align="left"))
    y += sub.height + 18 * s
    root.add(PathNode(f"M{margin},{y} H{width - margin}", Paint(stroke=ink, width=2 * s)))
    y += 28 * s

    # Left column: how it was made.
    col_w = (width - 3 * margin) * 0.36
    facts = [
        ("Rendered", data.rendered_at),
        ("Pages / panels", f"{data.pages} / {data.panels}"),
        *[(axis.title(), name) for axis, name in data.layers],
        ("Renderer", f"comicify render v{data.renderer_version}"),
        ("Pipeline", "prompt → clarification → structured intermediates → frozen art → "
                     "deterministic render"),
    ]
    ly = y
    for label, value in facts:
        lb = tx.block(label.upper(), small, col_w)
        root.add(lb.place(margin, ly, muted, align="left"))
        ly += lb.height
        vb = tx.block(value, body, col_w)
        root.add(vb.place(margin, ly, ink, align="left"))
        ly += vb.height + 12 * s

    credits = "Lettering: " + "; ".join(sorted({f"{f.family} (SIL Open Font License 1.1)"
                                                for f in data.fonts}))
    cb = tx.block(credits, small, col_w)
    root.add(cb.place(margin, max(ly + 10 * s, height - margin - cb.height), muted, align="left"))

    # Right column: token accounting table.
    tx0 = margin * 2 + col_w
    cols = [("Stage", 0.0), ("Model", 0.24), ("Files", 0.47), ("Input", 0.56),
            ("Output", 0.67), ("Cost", 0.8), ("Time", 0.92)]
    tw = width - margin - tx0
    row_h = body.line_height * 1.05
    ty = y
    for name, frac in cols:
        b = tx.block(name.upper(), small, tw)
        root.add(b.place(tx0 + frac * tw, ty, muted, align="left"))
    ty += row_h
    root.add(PathNode(f"M{tx0},{ty - 4 * s} H{width - margin}", Paint(stroke=muted, width=1 * s)))

    def row(values: list[str], font: tx.Font, color: str, shade: bool) -> None:
        nonlocal ty
        if shade:
            root.add(Rect(tx0 - 8 * s, ty - 2 * s, tw + 16 * s, row_h, Paint("#00000008")))
        for (_, frac), v in zip(cols, values):
            b = tx.block(v, font, tw * 0.3)
            root.add(b.place(tx0 + frac * tw, ty, color, align="left"))
        ty += row_h

    for i, r in enumerate(data.stages):
        u = r.usage
        model = ", ".join(m.split(":")[-1] for m in r.models)
        row([r.stage, model, str(r.artifacts),
             _k(u.input_tokens) if u else "—", _k(u.output_tokens) if u else "—",
             _usd(r.cost) if r.models != ["code"] else "", f"{u.duration_s:.0f}s" if u else "—"],
            small, ink, i % 2 == 0)

    t = data.total
    root.add(PathNode(f"M{tx0},{ty} H{width - margin}", Paint(stroke=ink, width=1.5 * s)))
    ty += 6 * s
    totals = ([_k(t.input_tokens), _k(t.output_tokens), _usd(data.total_cost),
               f"{t.duration_s:.0f}s"] if data.complete else ["—", "—", "—", "—"])
    row(["This comic", "", str(sum(r.artifacts for r in data.stages)), *totals], body, ink,
        False)
    notes = [f"Project to date: {data.spent_calls} LLM calls, {_k(data.spent.input_tokens)} input "
             f"+ {_k(data.spent.output_tokens)} output tokens, {_usd(data.spent_cost)} "
             f"(incl. clarification, regenerations, and other looks).",
             "Ranked by output tokens. Prices: genai-prices published rates; cache hits are "
             "free and shown at original cost."]
    if not data.complete:
        notes.append("— = produced before token accounting was recorded.")
    for n in notes:
        nb = tx.block(n, small, tw)
        root.add(nb.place(tx0, ty + 8 * s, muted, align="left"))
        ty += nb.height + 6 * s

    return ScenePage(page_id, width, height, theme.paper, root)
