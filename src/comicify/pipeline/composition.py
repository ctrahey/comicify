"""The composition solver: staging and lettering, planned together.

Comics are lettered by design, not by leftovers: the space for words is planned
when the panel is composed. For each panel this stage

  1. stages speakers so the first to speak stands on the left (reading order);
  2. measures the lettering the panel needs (reference letter metrics);
  3. makes headroom: lowers figures (or pulls back) so faces sit below the
     lettering zone the cinematography prefers;
  4. places captions, balloons, device text, and sound effects in reading
     order, with an explicit cost model: zone fit, nearness to the speaker,
     Z-path reading order, never covering faces or each other;
  5. lets loud sound effects break the frame when the cinematography allows.

The result is `structured/composition.yaml`: deterministic, art-style
independent, and editable. Every non-obvious decision is noted in `notes`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..models import (
    Brief, Character, CinematographyPack, Comic, Composition, Props, Set, ShotList,
)
from ..models.composition import (
    CameraFrame,
    FigurePlacement,
    LetterPlacement,
    NBox,
    NPoint,
    PanelComposition,
)
from ..models.direction import CaptionPlacement, FrameBreaks, LetteringFlow, LetteringZone
from ..models.shotlist import Angle, Panel, Shot, TextElement, TextKind
from ..render import text as tx
from ..render.geometry import (
    CLOSE_SHOTS, PLANE_SCALE, Box, figure, horizon_for, insert_screen, page_size, panel_frames,
    plane_ground,
)
from ..fonts import REGISTRY
from .core import Context, Job, Output

VERSION = 5

SPEECH = {TextKind.SPEECH, TextKind.THOUGHT, TextKind.WHISPER, TextKind.SHOUT}
BACKDROP_ZOOM = {
    Shot.ESTABLISHING: 1.0, Shot.WIDE: 1.0, Shot.MEDIUM: 1.15, Shot.OVER_THE_SHOULDER: 1.15,
    Shot.CLOSE_UP: 1.4, Shot.EXTREME_CLOSE_UP: 1.8, Shot.INSERT: 1.0,
}
BACKDROP_FOCUS_Y = {Angle.EYE_LEVEL: 0.78, Angle.LOW: 0.95, Angle.HIGH: 0.55, Angle.DUTCH: 0.78}
# How far below the frame feet may go, per shot, when making headroom.
MAX_GROUND = {Shot.ESTABLISHING: 1.0, Shot.WIDE: 1.02, Shot.MEDIUM: 1.3,
              Shot.OVER_THE_SHOULDER: 1.3}

# Reference lettering (px at 1080p). Looks refit text into the planned boxes.
REF = {"dialogue": ("Comic Neue", 700, 30), "caption": ("Comic Neue", 700, 26),
       "sfx": ("Bangers", 400, 64), "device": ("Work Sans", 700, 26)}
SFX_SIZE = {1: 0.7, 2: 1.0, 3: 1.45}


def _font(role: str, scale: float) -> tx.Font:
    family, weight, size = REF[role]
    return tx.Font(REGISTRY.resolve(family, weight), size * scale)


@dataclass
class Placed:
    box: Box  # normalized
    letter: LetterPlacement


@dataclass
class PanelSolver:
    panel: Panel
    index: int
    pw: float  # panel px
    ph: float
    scale: float  # page scale vs 1080p
    flow: LetteringFlow
    dims: dict[str, tuple[float, float]]  # character → (relative height, width ratio)
    holders: dict[str, str]  # prop id → holding character
    screen_box: Box | None  # insert-shot screen, normalized
    horizon: float = 0.6  # set horizon, before the camera angle
    notes: list[str] = field(default_factory=list)

    @property
    def aspect(self) -> float:
        return self.pw / self.ph

    @property
    def margin(self) -> tuple[float, float]:
        m = 14 * self.scale
        return m / self.pw, m / self.ph

    # --- measuring -----------------------------------------------------------------
    def shapes(self, el: TextElement) -> list[tuple[float, float]]:
        """Balloon shape options (normalized w, h): the same words wrapped wider or narrower.

        The preferred (~1.7:1) shape comes first; the solver may pick another to fit
        the air near the speaker, as a letterer would.
        """
        if el.kind not in SPEECH:
            return [self.measure(el)]
        font = _font("dialogue", self.scale * (1.15 if el.kind == TextKind.SHOUT else 1.0))
        pad = font.size * 0.6
        k = 1.35 if el.kind == TextKind.SHOUT else 1.22
        cap = min(0.7 * self.pw, 600 * self.scale)
        out = []
        for f in (1.0, 0.85, 0.7, 0.58, 0.48, 0.4):
            b = tx.block(el.text, font, cap * f)
            w, h = (b.width * 1.04 + 2 * pad) * k / self.pw, (b.height + 2 * pad) * k / self.ph
            if (round(w, 3), round(h, 3)) not in [(round(a, 3), round(c, 3)) for a, c in out]:
                out.append((min(w, 1.0), min(h, 0.9)))
        preferred = self.measure(el)
        return sorted(out, key=lambda wh: abs(wh[0] * self.pw / (wh[1] * self.ph) -
                                              preferred[0] * self.pw / (preferred[1] * self.ph)))

    def measure(self, el: TextElement) -> tuple[float, float]:
        """Planned box size (normalized) for a text element."""
        s, pw, ph = self.scale, self.pw, self.ph
        if el.kind in SPEECH:
            font = _font("dialogue", s * (1.15 if el.kind == TextKind.SHOUT else 1.0))
            # Letterers shape balloons, not just wrap them: pick the wrap width whose
            # block is closest to a comfortable ~1.7:1, within the panel's limits.
            cap = min(0.62 * pw, 520 * s)
            options = [tx.block(el.text, font, cap * f) for f in (1.0, 0.85, 0.7, 0.58, 0.48)]
            b = min(options, key=lambda o: abs((o.width + font.size * 1.2)
                                               / max(o.height + font.size * 1.2, 1) - 1.7))
            pad = font.size * 0.6
            k = 1.35 if el.kind == TextKind.SHOUT else 1.22  # room for round balloon shapes
            w, h = (b.width * 1.04 + 2 * pad) * k, (b.height + 2 * pad) * k
        elif el.kind == TextKind.CAPTION:
            font = _font("caption", s)
            bar = self.flow.captions == CaptionPlacement.TOP_BAR
            max_w = pw * (0.96 if bar else 0.55)
            b = tx.block(el.text, font, max_w)
            pad = font.size * 0.45
            w, h = (pw if bar else b.width + 2 * pad), b.height + 2 * pad
        elif el.kind == TextKind.DEVICE:
            font = _font("device", s)
            b = tx.block(el.text, font, min(0.46 * pw, 420 * s))
            pad = font.size * 0.6
            w, h = b.width + 2 * pad, b.height + 2 * pad
        else:  # sfx
            font = _font("sfx", s * SFX_SIZE[el.intensity])
            b = tx.block(el.text, font, 0.7 * pw)
            w, h = b.width * 1.15, b.height * 1.2
        return min(w / pw, 1.0), min(h / ph, 0.9)

    # --- figures -------------------------------------------------------------------
    def stage(self) -> list[FigurePlacement]:
        p = self.panel
        if p.shot == Shot.INSERT and self.screen_box is not None:
            return []
        figs = {c.character: FigurePlacement(
            character=c.character, x=c.placement.x, ground=c.placement.y,
            scale=c.placement.scale, stance=c.stance, plane=c.plane, facing=c.facing)
            for c in p.characters}

        # Depth: planes set size and where feet meet the ground (between horizon and
        # frame bottom), so figures aren't lined up on one baseline.
        if p.shot not in CLOSE_SHOTS:
            hz = horizon_for(self.horizon, p.angle)
            planes = {str(f.plane) for f in figs.values()}
            for f in figs.values():
                want = plane_ground(f.plane, hz)
                if len(planes) > 1 or str(f.plane) != "midground":
                    f.ground = round(max(f.ground, want) if str(f.plane) == "foreground"
                                     else want if abs(f.ground - want) > 0.12 else f.ground, 3)
                f.scale = round(f.scale * PLANE_SCALE[str(f.plane)], 3)

        # Reading order: the first to speak stands on the left.
        speakers = list(dict.fromkeys(t.speaker for t in sorted(p.text, key=lambda t: t.order)
                                      if t.kind in SPEECH and t.speaker in figs))
        if self.flow.speakers_left_to_right and len(speakers) >= 2:
            xs = sorted(figs[s].x for s in speakers)
            if [figs[s].x for s in speakers] != xs:
                for s, x in zip(speakers, xs):
                    figs[s].x = x
                centre = sum(xs) / len(xs)
                for s in speakers:
                    if figs[s].facing in ("left", "right"):
                        figs[s].facing = "right" if figs[s].x < centre else "left"
                self.notes.append(f"restaged speakers left-to-right in speaking order: "
                                  f"{', '.join(speakers)}")

        # Headroom: keep faces below the lettering the panel needs.
        need = self.headroom_needed()
        if need > 0 and p.shot not in CLOSE_SHOTS:
            for f in figs.values():
                g = self.figure(f)
                face_top = g.head[1] - g.height * 0.2
                if face_top >= need:
                    continue
                shift = need - face_top
                limit = MAX_GROUND.get(p.shot, 1.0)
                moved = min(shift, max(0.0, limit - f.ground))
                f.ground += moved
                rest = shift - moved
                if rest > 0.005:
                    k = max(0.72, 1 - rest / max(g.height, 1e-3))
                    f.scale = round(f.scale * k, 3)
                    self.notes.append(f"pulled back on {f.character} (scale ×{k:.2f}) "
                                      f"to make room for lettering")
                if moved > 0.005:
                    self.notes.append(f"lowered {f.character} by {moved:.2f} panel heights "
                                      f"for lettering headroom")
                f.ground = round(f.ground, 3)
        return list(figs.values())

    def figure(self, f: FigurePlacement):
        rel, width = self.dims.get(f.character, (1.0, 0.6))
        return figure(self.panel.shot, rel, f.x, f.ground, f.scale, f.stance, width)

    def headroom_needed(self) -> float:
        if self.flow.zone == LetteringZone.FREE:
            return 0.0
        mx, my = self.margin
        usable = 1 - 2 * mx
        rows, row_w, row_h = [], 0.0, 0.0
        for el in sorted(self.panel.text, key=lambda t: t.order):
            if el.kind not in SPEECH and el.kind != TextKind.CAPTION:
                continue
            w, h = self.measure(el)
            if row_w + w > usable and row_w:
                rows.append(row_h)
                row_w, row_h = 0.0, 0.0
            row_w += w + mx
            row_h = max(row_h, h)
        if row_h:
            rows.append(row_h)
        if not rows:
            return 0.0
        need = my + sum(rows) + my * len(rows)
        return min(need, self.flow.headroom + 0.12)

    # --- lettering -----------------------------------------------------------------
    def solve(self) -> PanelComposition:
        p = self.panel
        figures = self.stage()
        geo = {f.character: self.figure(f) for f in figures}
        faces = [g.keep_clear(self.aspect) for g in geo.values()]
        hard = [self.screen_box] if self.screen_box else []
        placed: list[Placed] = []
        letters: list[LetterPlacement] = []

        def anchor_of(speaker: str | None) -> NPoint | None:
            if speaker in geo:
                hx, hy = geo[speaker].head
                return NPoint(x=round(hx, 3), y=round(max(hy, 0.02), 3))
            holder = self.holders.get(speaker or "")
            if holder in geo:
                g = geo[holder]
                return NPoint(x=round(g.x, 3), y=round(g.ground - g.height * 0.5, 3))
            if self.screen_box and speaker:
                return NPoint(x=round(self.screen_box.cx, 3), y=round(self.screen_box.y, 3))
            return None

        ordered = sorted(enumerate(p.text),
                         key=lambda it: (it[1].kind != TextKind.CAPTION, it[1].order, it[0]))
        for i, el in ordered:
            w, h = self.measure(el)
            target = anchor_of(el.speaker)
            if el.kind == TextKind.CAPTION:
                box, breaks = self.place_caption(w, h, placed)
                letter = LetterPlacement(text=i, kind=el.kind, box=_nbox(box),
                                         breaks_frame=breaks)
            elif el.kind == TextKind.SFX:
                box, breaks = self.place_sfx(el, w, h, target, placed, faces, hard)
                sign = -1 if (self.index + i) % 2 == 0 else 1
                letter = LetterPlacement(
                    text=i, kind=el.kind, box=_nbox(box), breaks_frame=breaks,
                    rotation_deg=sign * (4 + 4 * el.intensity), size=SFX_SIZE[el.intensity],
                    tail_target=el.speaker)
            else:
                prev = placed[-1].box if placed else None
                box = self.place_balloon(el, self.shapes(el), target, prev, placed, faces, hard)
                letter = LetterPlacement(text=i, kind=el.kind, box=_nbox(box),
                                         tail_target=el.speaker, tail_to=target)
                # Consecutive balloons from one speaker connect instead of two tails.
                last = letters[-1] if letters else None
                if (last and last.kind in SPEECH and el.kind in SPEECH
                        and last.tail_target == el.speaker and el.speaker):
                    letter.chain_to = letters.index(last)
            placed.append(Placed(box, letter))
            letters.append(letter)

        camera = CameraFrame(
            zoom=BACKDROP_ZOOM[p.shot],
            focus=NPoint(x=round(sum(f.x for f in figures) / len(figures), 3) if figures
                         else 0.5, y=BACKDROP_FOCUS_Y[p.angle]))
        return PanelComposition(panel=p.id, aspect=round(self.aspect, 4), camera=camera,
                                horizon=round(horizon_for(self.horizon, p.angle), 3),
                                figures=figures, letters=letters, notes=self.notes)

    def place_caption(self, w: float, h: float, placed: list[Placed]) -> tuple[Box, bool]:
        mx, my = self.margin
        below = max((pl.box.y + pl.box.h for pl in placed
                     if pl.letter.kind == TextKind.CAPTION), default=None)
        mode = self.flow.captions
        if mode == CaptionPlacement.STRADDLE and self.flow.frame_breaks == \
                FrameBreaks.SFX_AND_CAPTIONS and below is None:
            return Box(mx * 2, -h / 2, w, h), True
        if mode == CaptionPlacement.TOP_BAR:
            return Box(0, below if below is not None else 0, 1.0, h), False
        return Box(mx, (below + my / 2) if below is not None else my, w, h), False

    def candidates(self, w: float, h: float, allow_outside: float = 0.0):
        mx, my = self.margin
        lo_x, hi_x = mx - allow_outside, 1 - mx - w + allow_outside
        lo_y, hi_y = my - allow_outside, 1 - my - h
        xs = [lo_x + (hi_x - lo_x) * k / 16 for k in range(17)] if hi_x > lo_x else [lo_x]
        steps = max(1, int((hi_y - lo_y) / 0.02))
        ys = [lo_y + (hi_y - lo_y) * k / steps for k in range(steps + 1)] if hi_y > lo_y \
            else [lo_y]
        return xs, ys

    def place_balloon(self, el: TextElement, shapes: list[tuple[float, float]],
                      target: NPoint | None, prev: Box | None, placed: list[Placed],
                      faces: list[Box], hard: list[Box]) -> Box:
        w, h = shapes[0]
        zone = self.flow.zone
        mx, my = self.margin
        tx_, ty = (target.x, target.y) if target else (0.5, 0.6)
        letters = [pl.box for pl in placed]

        def cost(b: Box, face_weight: float) -> float:
            c = 0.0
            # Near the speaker, horizontally; above them is best.
            c += abs(b.cx - tx_) * 3.0
            if b.y + b.h > ty:  # below the mouth: tails point up — avoid
                c += 1.5 + (b.y + b.h - ty) * 3
            if zone == LetteringZone.TOP_BAND:
                c += b.y * 4
            elif zone == LetteringZone.EDGES:
                c += min(b.y, b.x, 1 - b.x - b.w) * 6
            elif zone == LetteringZone.CORNERS:
                c += min(math.hypot(b.x, b.y), math.hypot(1 - b.x - b.w, b.y)) * 4
            else:  # free: close to the head
                c += math.hypot(b.cx - tx_, (b.y + b.h) - (ty - 0.05)) * 2
            # Z-path reading order: later balloons go right of or below earlier ones.
            if prev is not None and b.cx < prev.cx - 0.02 and b.y < prev.y + prev.h * 0.6:
                c += 3.0
            c += face_weight * sum(b.overlap_area(f) for f in faces) / max(b.w * b.h, 1e-6)
            return c

        # Keep figures clear at every size before ever covering one.
        for face_hard, shrink in [(True, 1.0), (True, 0.88), (True, 0.76),
                                  (False, 1.0), (False, 0.88), (False, 0.76)]:
            best: tuple[float, Box] | None = None
            for rank, (w0, h0) in enumerate(shapes):
                sw, sh = w0 * shrink, h0 * shrink
                xs, ys = self.candidates(sw, sh)
                for x in xs:
                    for y in ys:
                        b = Box(x, y, sw, sh)
                        if any(b.overlaps(o, 0.012) for o in letters + hard):
                            continue
                        if face_hard and any(b.overlaps(f) for f in faces):
                            continue
                        c = cost(b, 0.0 if face_hard else 4.0) + 0.12 * rank
                        if best is None or c < best[0]:
                            best = (c, b)
            if best:
                if shrink < 1.0:
                    self.notes.append(f"tightened a crowded balloon to {shrink:.0%}")
                if not face_hard:
                    self.notes.append("no clear air: a balloon overlaps a figure")
                return best[1]
        self.notes.append("panel is overcrowded: lettering overlaps; consider fewer words")
        xs, ys = self.candidates(w * 0.76, h * 0.76)
        return min((Box(x, y, w * 0.76, h * 0.76) for x in xs for y in ys),
                   key=lambda b: sum(b.overlap_area(o) for o in letters))

    def place_sfx(self, el: TextElement, w: float, h: float, target: NPoint | None,
                  placed: list[Placed], faces: list[Box], hard: list[Box]) -> tuple[Box, bool]:
        breaks_ok = (el.intensity >= 3 and self.flow.frame_breaks != FrameBreaks.NONE)
        outside = 0.14 if breaks_ok else 0.0
        tx_, ty = (target.x, target.y - 0.1) if target else (0.5, 0.35)
        letters = [pl.box for pl in placed]
        xs, ys = self.candidates(w, h, allow_outside=outside)
        best: tuple[float, Box] | None = None
        for x in xs:
            for y in ys:
                b = Box(x, y, w, h)
                if any(b.overlaps(o, 0.01) for o in letters + hard):
                    continue
                c = math.hypot(b.cx - tx_, b.cy - ty) * 2
                c += 3 * sum(b.overlap_area(f) for f in faces) / max(b.w * b.h, 1e-6)
                if breaks_ok and (b.y < 0 or b.x < 0 or b.x + b.w > 1):
                    c -= 0.25  # the loudest moment earns the frame break
                if best is None or c < best[0]:
                    best = (c, b)
        box = best[1] if best else Box(0.5 - w / 2, 0.3, w, h)
        breaks = box.y < 0 or box.x < 0 or box.x + box.w > 1 or box.y + box.h > 1
        if breaks:
            self.notes.append(f"'{el.text}' breaks the frame")
        return box, breaks


def _nbox(b: Box) -> NBox:
    return NBox(x=round(b.x, 4), y=round(b.y, 4), w=round(b.w, 4), h=round(b.h, 4))


def compose_plan(brief: Brief, comic: Comic, cine: CinematographyPack, shotlist: ShotList,
                 dims: dict[str, tuple[float, float]], props: Props,
                 horizons: dict[str, float] | None = None) -> Composition:
    frames = panel_frames(brief, comic, cine)
    _, page_h = page_size(brief)
    scale = page_h / 1080
    holders: dict[str, str] = {}
    panels = []
    device_props = {p.id: p for p in props.props}
    for i, panel in enumerate(shotlist.panels):
        frame = frames[panel.id].box
        for pp in panel.props:
            if pp.held_by:
                holders[pp.prop] = pp.held_by
        screen = None
        if panel.shot == Shot.INSERT and any(
                pp.screen or device_props.get(pp.prop, None) and device_props[pp.prop].screens
                for pp in panel.props):
            screen = insert_screen(bool(panel.text), frame.w / frame.h)
        solver = PanelSolver(panel, i, frame.w, frame.h, scale, cine.lettering, dims,
                             dict(holders), screen, (horizons or {}).get(panel.set, 0.6))
        panels.append(solver.solve())
        holders = {}
    return Composition(panels=panels)


def character_dims(st) -> dict[str, tuple[float, float]]:
    out = {}
    for c in st.character_ids():
        v = st.character(c).visual
        out[c] = (v.relative_height, v.width_ratio)
    return out


class CompositionStage:
    name = "composition"

    def jobs(self, ctx: Context) -> list[Job]:
        st = ctx.store
        inputs = [st.path(ShotList), st.path(Comic), st.path(Brief), st.path(CinematographyPack),
                  st.path(Props), *(st.path(Character, c) for c in st.character_ids()),
                  *(st.path(Set, s) for s in st.set_ids())]

        def produce() -> Output:
            horizons = {s: st.set(s).horizon for s in st.set_ids()}
            return Output(compose_plan(st.brief(), st.comic(), st.cinematography(),
                                       st.shotlist(), character_dims(st), st.props(), horizons))

        return [Job(stage=self.name, key=self.name, output=st.path(Composition),
                    produced_by=f"composition@code-v{VERSION}", inputs=inputs,
                    produce=produce)]
