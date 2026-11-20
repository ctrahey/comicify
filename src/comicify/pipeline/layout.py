"""Deterministic page layout: shot list + brief + cinematography → comic.yaml.

The cinematography pack's grid policy shapes the page:

  regular     uniform cells, panel weight ignored (nine-panel grid, planimetric)
  tiers       rows of panels; weight widens a panel within its row
  widescreen  full-width letterbox panels stacked
  varied      like tiers, with the most freedom in panel sizes (row spans: future)

Layout is lettering-aware: a panel carrying heavy text is widened (its weight
raised), as a letterer would ask the penciller for room. Panels pack in reading
order into the smallest grid (within the pack's bounds) that fits the brief's
target page count. If even the largest grid can't, panel
weights are relaxed before adding pages. Rows never have holes: the last panel
in a short row stretches to fill it.
"""

from __future__ import annotations

import math

from ..models import Brief, CinematographyPack, Comic, Page, PanelSlot, ShotList
from ..models.brief import PageAspect
from ..models.direction import GridPolicy
from .core import Context, Job, Output

VERSION = 3

# Reference lettering cost: px² of panel per character of text (balloon included),
# at 1080p, and the share of a panel lettering may take before it's widened.
CHAR_AREA = {"caption": 700.0, "sfx": 900.0, "default": 950.0}
TEXT_SHARE_LIMIT = 0.28

# Preferred columns-per-row ratio by page aspect (wide slides favor more columns).
ASPECT_RATIO = {PageAspect.WIDESCREEN: 1.6, PageAspect.STANDARD: 1.25,
                PageAspect.PORTRAIT: 0.7, PageAspect.STRIP: 4.0}


def candidate_grids(cine: CinematographyPack, aspect: str) -> list[tuple[int, int]]:
    g = cine.grid
    if g.policy == GridPolicy.WIDESCREEN:
        return [(r, 1) for r in range(1, g.max_rows + 1)]
    want = ASPECT_RATIO[PageAspect(aspect)]
    grids = [(r, c) for r in range(1, g.max_rows + 1) for c in range(1, g.max_cols + 1)]
    return sorted(grids, key=lambda rc: (rc[0] * rc[1], abs(rc[1] / rc[0] - want)))


def text_load(panel) -> float:
    """Estimated lettering area (px² at 1080p) a panel needs."""
    return sum(len(t.text) * CHAR_AREA.get(t.kind, CHAR_AREA["default"]) for t in panel.text)


def layout(shotlist: ShotList, brief: Brief, cine: CinematographyPack) -> Comic:
    panels = shotlist.panels
    policy = cine.grid.policy
    grids = candidate_grids(cine, brief.aspect)
    target = brief.length.target_pages

    uniform = policy in (GridPolicy.REGULAR, GridPolicy.WIDESCREEN)
    weights = [1 if uniform else min(p.weight, 3) for p in panels]
    if not uniform:
        # Widen text-heavy panels: estimate a one-column cell of the likely grid.
        rows0, cols0 = max(grids, key=lambda rc: rc[0] * rc[1])
        cell = (1840 / cols0) * (1000 / rows0)
        for i, p in enumerate(panels):
            if text_load(p) / (cell * weights[i]) > TEXT_SHARE_LIMIT:
                weights[i] = min(weights[i] + 1, 3)
    biggest = max(grids, key=lambda rc: rc[0] * rc[1])
    capacity = biggest[0] * biggest[1]
    units = sum(min(w, biggest[1]) for w in weights)
    if units > capacity * target and \
            math.ceil(len(panels) / capacity) < math.ceil(units / capacity):
        weights = [1] * len(panels)  # relax emphasis only if that saves a page
    per_page = math.ceil(sum(weights) / max(1, target))
    rows, cols = next((g for g in grids if g[0] * g[1] >= per_page), biggest)

    pages: list[Page] = []
    slots: list[PanelSlot] = []
    row, col = 0, 0

    def close_row() -> None:
        if slots and slots[-1].row == row and col < cols:
            slots[-1].col_span += cols - col

    def close_page(final: bool) -> None:
        if slots:
            used = max(s.row for s in slots) + 1
            pages.append(Page(id=f"page-{len(pages) + 1}", rows=used if final else rows,
                              cols=cols, slots=list(slots)))
            slots.clear()

    for p, w in zip(panels, weights):
        span = min(w, cols)
        if col + span > cols:
            close_row()
            row, col = row + 1, 0
        if row >= rows:
            close_page(final=False)
            row, col = 0, 0
        slots.append(PanelSlot(panel=p.id, row=row, col=col, col_span=span))
        col += span
    close_row()
    close_page(final=True)
    return Comic(pages=pages)


class LayoutStage:
    name = "layout"

    def jobs(self, ctx: Context) -> list[Job]:
        st = ctx.store
        return [Job(
            stage=self.name,
            key=self.name,
            output=st.path(Comic),
            produced_by=f"layout@code-v{VERSION}",
            inputs=[st.path(ShotList), st.path(Brief), st.path(CinematographyPack)],
            produce=lambda: Output(layout(st.shotlist(), st.brief(), st.cinematography())),
        )]
