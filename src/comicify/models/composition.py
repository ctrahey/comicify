"""Composition: each panel's staging and lettering plan (the comic's "thumbnails").

Coordinates are panel-normalized: (0, 0) is the panel's top-left, (1, 1) its
bottom-right. Values outside 0..1 deliberately break the frame.

The composition is solved from the shot list, layout, and cinematography, and
is independent of the art style: switching looks keeps every balloon where it
is (text is refit to each look's lettering). Edit it to move a balloon, retarget
a tail, enlarge a sound effect, or let it burst out of the panel.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .base import Artifact, Model, Slug
from .shotlist import Plane, Stance, TextKind


class NBox(Model):
    x: float = Field(ge=-0.5, le=1.5)
    y: float = Field(ge=-0.5, le=1.5)
    w: float = Field(gt=0, le=2)
    h: float = Field(gt=0, le=2)


class NPoint(Model):
    x: float = Field(ge=-0.5, le=1.5)
    y: float = Field(ge=-0.5, le=1.5)


class CameraFrame(Model):
    zoom: float = Field(default=1.0, ge=0.5, le=3, description="Push into the backdrop.")
    focus: NPoint = Field(default_factory=lambda: NPoint(x=0.5, y=0.78),
                          description="Backdrop point kept under the panel's same point.")


class FigurePlacement(Model):
    character: Slug
    x: float = Field(ge=-0.2, le=1.2, description="Horizontal center.")
    ground: float = Field(ge=0, le=1.6, description="Where the feet are (may be below frame).")
    scale: float = Field(default=1.0, gt=0, le=4)
    stance: Stance = Stance.STANDING
    plane: Plane = Plane.MIDGROUND
    facing: Literal["left", "right", "viewer", "away"] = "viewer"


class LetterPlacement(Model):
    text: int = Field(ge=0, description="Index into the shot-list panel's `text` list.")
    kind: TextKind
    box: NBox
    tail_target: Slug | None = Field(default=None, description="Character or prop spoken by.")
    tail_to: NPoint | None = Field(default=None, description="Planned tail tip (estimate).")
    chain_to: int | None = Field(
        default=None, description="Letter index this balloon connects to (same speaker).")
    rotation_deg: float = Field(default=0, ge=-45, le=45)
    size: float = Field(default=1.0, gt=0, le=4, description="Lettering scale (sfx).")
    breaks_frame: bool = Field(default=False, description="Drawn above the panel border.")


class PanelComposition(Model):
    panel: Slug
    aspect: float = Field(gt=0, description="Panel width / height when solved.")
    camera: CameraFrame = Field(default_factory=CameraFrame)
    horizon: float = Field(default=0.6, ge=-0.5, le=1.5,
                           description="Horizon height in the panel (camera angle applied).")
    figures: list[FigurePlacement] = Field(default_factory=list)
    letters: list[LetterPlacement] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list, description="Decisions the solver made.")


class Composition(Artifact):
    KIND = "composition"

    panels: list[PanelComposition]

    def for_panel(self, panel_id: str) -> PanelComposition | None:
        return next((p for p in self.panels if p.panel == panel_id), None)
