"""Shared geometry: pages, panels, and figures.

The composition solver (planning) and the compositor (rendering) both use these
functions, so they can never disagree about where a panel, a figure, or a face is.
Figure geometry is in *panel-normalized* units: x and y in 0..1 of the panel's
width and height.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import Brief, CinematographyPack, Comic
from ..models.brief import PageAspect
from ..models.shotlist import Shot, Stance
from ..svg import CHARACTER_CANVAS

PAGE_SIZES = {
    PageAspect.WIDESCREEN: (1920, 1080),
    PageAspect.STANDARD: (1600, 1200),
    PageAspect.PORTRAIT: (1240, 1754),
    PageAspect.STRIP: (2400, 800),
}
MARGIN_PX = 40  # at 1080px page height
TITLE_BAND_PX = 92  # first page only

# Height of a relative_height=1.0 figure as a fraction of panel height, per shot.
FIGURE_SCALE = {
    Shot.ESTABLISHING: 0.42, Shot.WIDE: 0.58, Shot.MEDIUM: 0.85, Shot.OVER_THE_SHOULDER: 0.85,
    Shot.CLOSE_UP: 1.5, Shot.EXTREME_CLOSE_UP: 2.4, Shot.INSERT: 0.5,
}
CLOSE_SHOTS = {Shot.CLOSE_UP, Shot.EXTREME_CLOSE_UP}
CLOSE_UP_HEAD_Y = 0.42  # where close-ups put the face, as a fraction of panel height
# How tall a pose is relative to standing (drawings keep the same scale).
STANCE_HEIGHT = {Stance.STANDING: 1.0, Stance.CROUCHING: 0.7, Stance.SITTING: 0.62,
                 Stance.LYING: 0.32}


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    w: float
    h: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    def overlaps(self, other: Box, pad: float = 0.0) -> bool:
        return not (self.x + self.w + pad <= other.x or other.x + other.w + pad <= self.x or
                    self.y + self.h + pad <= other.y or other.y + other.h + pad <= self.y)

    def overlap_area(self, other: Box) -> float:
        w = min(self.x + self.w, other.x + other.w) - max(self.x, other.x)
        h = min(self.y + self.h, other.y + other.h) - max(self.y, other.y)
        return max(0.0, w) * max(0.0, h)

    def scaled(self, sx: float, sy: float, ox: float = 0, oy: float = 0) -> Box:
        return Box(ox + self.x * sx, oy + self.y * sy, self.w * sx, self.h * sy)


@dataclass(frozen=True)
class PanelFrame:
    panel: str
    page: int
    box: Box  # page pixels


def page_size(brief: Brief) -> tuple[int, int]:
    return PAGE_SIZES[PageAspect(brief.aspect)]


def panel_frames(brief: Brief, comic: Comic, cine: CinematographyPack) -> dict[str, PanelFrame]:
    width, height = page_size(brief)
    s = height / 1080
    margin, gutter = MARGIN_PX * s, cine.grid.gutter_px * s
    out = {}
    for index, page in enumerate(comic.pages):
        top = margin + (TITLE_BAND_PX * s if index == 0 else 0)
        area = Box(margin, top, width - 2 * margin, height - top - margin)
        cell_w = (area.w - gutter * (page.cols - 1)) / page.cols
        cell_h = (area.h - gutter * (page.rows - 1)) / page.rows
        for slot in page.slots:
            out[slot.panel] = PanelFrame(slot.panel, index, Box(
                area.x + slot.col * (cell_w + gutter), area.y + slot.row * (cell_h + gutter),
                cell_w * slot.col_span + gutter * (slot.col_span - 1),
                cell_h * slot.row_span + gutter * (slot.row_span - 1)))
    return out


@dataclass(frozen=True)
class Figure:
    """A figure's frame in panel-normalized units."""

    x: float  # horizontal center
    ground: float  # where the body rests
    height: float  # height in this pose (relative height and stance applied)
    width: float  # silhouette width, in panel heights
    head: tuple[float, float]  # estimated face center

    @property
    def top(self) -> float:
        return self.ground - self.height

    def keep_clear(self, aspect: float) -> Box:
        """The upper body, where the face is: lettering should not cover it.

        Head position varies by species and pose (a tortoise's is at the front),
        so the whole upper silhouette is protected, not a guessed point.
        """
        w = self.width / aspect
        return Box(self.x - w / 2, self.top - self.height * 0.06, w, self.height * 0.62)


def figure(shot: Shot, rel_height: float, x: float, ground: float, scale: float,
           stance: Stance = Stance.STANDING, width_ratio: float = 0.6) -> Figure:
    standing = FIGURE_SCALE[Shot(shot)] * scale * rel_height
    h = standing * STANCE_HEIGHT[Stance(stance)]
    w = standing * width_ratio * (1.0 if Stance(stance) != Stance.LYING else 2.2)
    head_y = ground - h * 0.86
    if Shot(shot) in CLOSE_SHOTS:
        ground = CLOSE_UP_HEAD_Y + h * 0.86
        head_y = CLOSE_UP_HEAD_Y
    return Figure(x, ground, h, w, (x, head_y))


def insert_screen(has_text: bool, aspect: float = 1.0) -> Box:
    """Where an insert shot puts the device (normalized).

    Wide panels put the device on the right and leave the left for lettering;
    narrow panels put it below the lettering.
    """
    if not has_text:
        return Box(0.15, 0.08, 0.7, 0.84)
    if aspect >= 1.3:
        return Box(0.52, 0.06, 0.44, 0.88)
    return Box(0.2, 0.4, 0.6, 0.56)


def canvas_units_per_panel_height(shot: Shot, scale: float) -> float:
    """Character-canvas units → panel-height fraction for a given shot."""
    return FIGURE_SCALE[Shot(shot)] * scale / CHARACTER_CANVAS.figure_height
