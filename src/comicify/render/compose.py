"""Compose: structured intermediates + one look's assets → a resolved Scene.

Reads only `structured/` and `assets/<look>/` (never the author's prompt). All
layout decisions are made here; backends only serialize. Missing assets render
as labeled placeholders, so the comic can be blocked out before any art exists.

Staging and lettering come from the composition (structured/composition.yaml);
this module realizes them for one look. Layers, back to front:

    per panel:  art (backdrop, figures, props, screens; group effects apply)
                tone (halftone overlays)
                letters (balloons, captions, SFX)  ← crisp: no effects
                frame (panel border)
    per page:   frame-breaking letters, above every panel and gutter
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from .. import svg
from ..models import Character, Panel, Props, Set, ShotList
from ..models.composition import FigurePlacement, PanelComposition
from ..models.direction import Grain, Halftone
from ..models.product import Screen
from ..models.shotlist import Angle, Shot
from ..models.style import TextRole
from ..store import Store
from ..svg import CHARACTER_CANVAS, SET_CANVAS
from ..pipeline.composition import character_dims, compose_plan
from . import text as tx
from .geometry import (
    CLOSE_SHOTS, CLOSE_UP_HEAD_Y, FIGURE_SCALE, PAGE_SIZES, STANCE_HEIGHT, Box, insert_screen,
    panel_frames,
)
from .lettering import Layers, Letterer, Point
from .scene import Asset, Group, Node, Overlay, Paint, Rect, Scene, ScenePage
from .screens import Box as ScreenBox
from .screens import device_frame, screen_nodes
from .theme import Theme, fallback_style

# How far the camera pushes into the backdrop, per shot.
BACKDROP_ZOOM = {
    Shot.ESTABLISHING: 1.0, Shot.WIDE: 1.0, Shot.MEDIUM: 1.15, Shot.OVER_THE_SHOULDER: 1.15,
    Shot.CLOSE_UP: 1.4, Shot.EXTREME_CLOSE_UP: 1.8, Shot.INSERT: 1.0,
}
# Vertical focus of the backdrop: low angles see more sky, high angles more ground.
BACKDROP_FOCUS_Y = {Angle.EYE_LEVEL: 0.78, Angle.LOW: 0.95, Angle.HIGH: 0.55, Angle.DUTCH: 0.78}


@dataclass
class Staged:
    """Where a character ended up in a panel (for tails)."""

    head: Point
    hand: Point


class Composer:
    def __init__(self, store: Store):
        self.store = store
        self.brief = store.brief()
        art = store.art()
        style_path = store.look_dir / "style.yaml"
        style = store.style() if style_path.exists() else fallback_style(art)
        self.theme = Theme(style, art, store.cinematography())
        self.product = store.product()
        self.shotlist: ShotList = store.shotlist()
        self.comic = store.comic()
        self.props: Props = store.props()
        self.characters: dict[str, Character] = {
            cid: store.character(cid) for cid in store.character_ids()}
        self.sets: dict[str, Set] = {sid: store.set(sid) for sid in store.set_ids()}
        self.screens: dict[str, Screen] = {s.id: s for s in self.product.screens}
        self.panels: dict[str, Panel] = {p.id: p for p in self.shotlist.panels}
        self.width, self.height = PAGE_SIZES[self.brief.aspect]
        self.scale = self.height / 1080
        self.frames = panel_frames(self.brief, self.comic, self.theme.cine)
        plan_path = store.project.artifact_path("composition")
        # The composition is part of the storyboard; solve it on the fly only if
        # it hasn't been generated yet (e.g. older projects).
        self.plan = store.composition() if plan_path.exists() else compose_plan(
            self.brief, self.comic, self.theme.cine, self.shotlist, character_dims(store),
            self.props)
        self.letterer = Letterer(self.theme, self.scale)
        self.missing: list[str] = []
        self._anchor_cache: dict[Path, dict[str, tuple[float, float]]] = {}
        effects = self.theme.art.effects
        self.group_effects = [e for e in effects if e.kind in
                              ("monochrome", "posterize", "wobble", "misregister")]
        self.halftones = [e for e in effects if isinstance(e, Halftone)]
        self.grain = [e for e in effects if isinstance(e, Grain)]

    # --- pages -------------------------------------------------------------------
    def compose(self) -> Scene:
        pages = [self._page(i, page) for i, page in enumerate(self.comic.pages)]
        faces = {self.theme.font(role).face for role in TextRole}
        return Scene(pages, sorted(faces, key=lambda f: f.key))

    def _page(self, index: int, page) -> ScenePage:
        th, s = self.theme, self.scale
        margin = 40 * s
        root = Group(label=page.id)
        if index == 0:
            font = th.font(TextRole.TITLE, s)
            b = tx.fit(self.brief.title, font, self.width - 2 * margin, 80 * s)
            root.add(b.place(margin, margin * 0.6, th.ink, align="left"))
        foot = tx.block(f"{index + 1} / {len(self.comic.pages)}",
                        th.font(TextRole.CAPTION, s * 0.6), 200 * s)
        root.add(foot.place(self.width - margin - foot.width, self.height - margin * 0.85, th.ink))

        above = Layers()  # frame-breaking lettering, drawn over every panel
        for slot in page.slots:
            root.add(self._panel(self.panels[slot.panel], self.frames[slot.panel].box, above))
        root.add(*above.nodes(f"{page.id}-breakouts",
                              [e for e in self.group_effects if e.kind in ("wobble", "misregister")]))
        for g in self.grain:
            root.add(Overlay(0, 0, self.width, self.height, g, s))
        return ScenePage(page.id, self.width, self.height, th.paper, root)

    # --- panels ------------------------------------------------------------------
    def _panel(self, panel: Panel, box: Box, above: Layers) -> Group:
        th = self.theme
        plan = self.plan.for_panel(panel.id) or PanelComposition(panel=panel.id, aspect=1.0)
        radius = th.art.panel.corner_radius_px * self.scale
        clip = Rect(box.x, box.y, box.w, box.h, Paint(), rx=radius)
        art = Group(label=f"panel-{panel.id}-art", effects=list(self.group_effects))
        staged: dict[str, Staged] = {}
        anchors: dict[str, Point] = {}

        if panel.shot == Shot.INSERT and (screen := self._insert_screen(panel)):
            prop_id, screen_obj, device = screen
            art.add(Rect(box.x, box.y, box.w, box.h, Paint(th.palette_color(
                "base", "background", "wall", "sky", fallback=th.paper))))
            area = insert_screen(bool(panel.text), box.w / box.h).scaled(box.w, box.h, box.x, box.y)
            frame, screen_box = device_frame(device, ScreenBox(area.x, area.y, area.w, area.h), th)
            art.add(*frame, screen_nodes(screen_obj, screen_box, th))
            anchors[prop_id] = Point(screen_box.x + screen_box.w / 2, screen_box.y)
        else:
            art.add(*self._backdrop(panel, plan, box))
            depth = {c.character: c.placement.depth for c in panel.characters}
            for f in sorted(plan.figures, key=lambda f: depth.get(f.character, 0)):
                nodes, st = self._character(panel, f, box)
                art.add(*nodes)
                staged[f.character] = st
            for pp in panel.props:
                holder = staged.get(pp.held_by or "")
                if holder:
                    anchors[pp.prop] = holder.hand
                elif pp.placement:
                    nodes, at = self._prop(pp.prop, pp.placement, box)
                    art.add(*nodes)
                    anchors[pp.prop] = at

        if panel.angle == Angle.DUTCH and panel.tilt_deg:
            t = math.radians(abs(panel.tilt_deg))
            k = math.cos(t) + math.sin(t) * max(box.w / box.h, box.h / box.w)
            cx, cy = box.x + box.w / 2, box.y + box.h / 2
            art = Group([art], transform=f"translate({cx:.1f},{cy:.1f}) "
                        f"rotate({panel.tilt_deg:.1f}) scale({k:.3f}) "
                        f"translate({-cx:.1f},{-cy:.1f})", label=f"panel-{panel.id}-camera")

        tone = [Overlay(box.x, box.y, box.w, box.h, h, self.scale) for h in self.halftones
                if h.target == "panel" or panel.shot != Shot.INSERT]

        inside = Layers()
        boxes = [lp.box for lp in plan.letters]
        for lp in plan.letters:
            if lp.text >= len(panel.text):
                continue  # composition out of date with the shot list; skip gracefully
            el = panel.text[lp.text]
            lbox = Box(box.x + lp.box.x * box.w, box.y + lp.box.y * box.h,
                       lp.box.w * box.w, lp.box.h * box.h)
            target = None
            if lp.tail_target in staged:
                target = staged[lp.tail_target].head
            elif lp.tail_target in anchors:
                target = anchors[lp.tail_target]
            elif lp.tail_to is not None:
                target = Point(box.x + lp.tail_to.x * box.w, box.y + lp.tail_to.y * box.h)
            chained = None
            if lp.chain_to is not None and 0 <= lp.chain_to < len(boxes):
                cb = boxes[lp.chain_to]
                chained = Box(box.x + cb.x * box.w, box.y + cb.y * box.h, cb.w * box.w,
                              cb.h * box.h)
            self.letterer.draw(lp, el, lbox, target, chained,
                               above if lp.breaks_frame else inside)

        shape_fx = [e for e in self.group_effects if e.kind in ("wobble", "misregister")]
        content = Group([art, *tone, *inside.nodes(f"panel-{panel.id}-letters", shape_fx)],
                        clip=clip,
                        label=f"panel-{panel.id}")
        border = th.panel_border(self.scale)
        frame = [Rect(box.x, box.y, box.w, box.h, border, rx=radius)] if border else []
        return Group([content, *frame], label=f"panel-{panel.id}-frame")

    def _insert_screen(self, panel: Panel):
        for pp in panel.props:
            prop = next((p for p in self.props.props if p.id == pp.prop), None)
            screen_id = pp.screen or (prop.screens[0] if prop and prop.screens else None)
            if prop and screen_id in self.screens:
                return prop.id, self.screens[screen_id], prop.device or "device"
        return None

    def _backdrop(self, panel: Panel, plan: PanelComposition, box: Box) -> list[Node]:
        nodes: list[Node] = [Rect(box.x, box.y, box.w, box.h,
                                  Paint(self.theme.set_sky(panel.set)))]
        path = self.store.set_backdrop_path(panel.set)
        if not path.exists():
            self.missing.append(self.store.project.rel(path))
            return nodes
        cam = plan.camera
        scale = max(box.w / SET_CANVAS.width, box.h / SET_CANVAS.height) * cam.zoom
        w, h = SET_CANVAS.width * scale, SET_CANVAS.height * scale
        fx, fy = cam.focus.x, cam.focus.y
        x = min(box.x, max(box.x + box.w - w, box.x + fx * box.w - fx * w))
        y = min(box.y, max(box.y + box.h - h, box.y + fy * box.h - fy * h))
        nodes.append(Asset(f"set-{panel.set}", path, x, y, w, h))
        return nodes

    def _anchors(self, path: Path) -> dict[str, tuple[float, float]]:
        if path not in self._anchor_cache:
            self._anchor_cache[path] = svg.anchors(path.read_text("utf-8"))
        return self._anchor_cache[path]

    def _character(self, panel: Panel, f: FigurePlacement, box: Box
                   ) -> tuple[list[Node], Staged]:
        ch = self.characters.get(f.character)
        rel = ch.visual.relative_height if ch else 1.0
        figure_px = box.h * FIGURE_SCALE[panel.shot] * f.scale  # px for rel=1.0
        k = figure_px / CHARACTER_CANVAS.figure_height  # canvas units → px
        canvas_px = CHARACTER_CANVAS.width * k
        fig_h = rel * figure_px
        cx = box.x + f.x * box.w
        ground = box.y + f.ground * box.h

        path = self.store.character_pose_path(f.character, *self._pose(panel, f.character))
        mirror = f.facing == "left"
        found = path.exists()
        marks = self._anchors(path) if found else {}
        unit_h = rel * CHARACTER_CANVAS.figure_height * STANCE_HEIGHT[f.stance]
        head_u = marks.get("head", (CHARACTER_CANVAS.width / 2,
                                    CHARACTER_CANVAS.ground - unit_h * 0.86))
        hand_u = marks.get("hand", (CHARACTER_CANVAS.width / 2,
                                    CHARACTER_CANVAS.ground - unit_h * 0.5))
        if panel.shot in CLOSE_SHOTS:  # frame on the actual face
            ground = box.y + box.h * CLOSE_UP_HEAD_Y + (CHARACTER_CANVAS.ground - head_u[1]) * k

        x0 = cx - canvas_px / 2
        y0 = ground - CHARACTER_CANVAS.ground * k

        def to_page(u: tuple[float, float]) -> Point:
            ux = CHARACTER_CANVAS.width - u[0] if mirror else u[0]
            return Point(x0 + ux * k, y0 + u[1] * k)

        staged = Staged(head=to_page(head_u), hand=to_page(hand_u))
        if not found:
            self.missing.append(self.store.project.rel(path))
            pose, expr = self._pose(panel, f.character)
            return self._placeholder(f"{f.character}\n{pose} / {expr}",
                                     Box(cx - fig_h * 0.25, ground - fig_h, fig_h * 0.5,
                                         fig_h)), staged
        pose, expr = self._pose(panel, f.character)
        ref = f"char-{f.character}-{pose}-{expr}"
        return [Asset(ref, path, x0, y0, canvas_px, canvas_px, mirror=mirror)], staged

    @staticmethod
    def _pose(panel: Panel, character: str) -> tuple[str, str]:
        c = next(c for c in panel.characters if c.character == character)
        return c.pose, c.expression

    def _prop(self, prop_id: str, placement, box: Box) -> tuple[list[Node], Point]:
        size = box.h * 0.25 * placement.scale
        cx, ground = box.x + placement.x * box.w, box.y + placement.y * box.h
        at = Point(cx, ground - size)
        path = self.store.prop_art_path(prop_id)
        if not path.exists():
            self.missing.append(self.store.project.rel(path))
            return self._placeholder(prop_id, Box(cx - size / 2, ground - size, size, size)), at
        return [Asset(f"prop-{prop_id}", path, cx - size / 2, ground - size, size, size)], at

    def _placeholder(self, label: str, b: Box) -> list[Node]:
        th = self.theme
        font = th.font(TextRole.CAPTION, self.scale * 0.6)
        t = tx.fit(label, font, b.w * 1.6, b.h)
        return [Rect(b.x, b.y, b.w, b.h, Paint(th.color("placeholder"), th.ink, 2, dash="8 6"),
                     rx=b.w * 0.3),
                t.place(b.x + b.w / 2, b.y + b.h / 2 - t.height / 2, th.ink)]
