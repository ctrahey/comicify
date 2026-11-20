"""Typed access to a project's intermediates and assets.

The storyboard (story, characters, sets, shot list, layout) is art-agnostic and
lives in structured/. Each art *look* has its own namespace:

    structured/direction.yaml                              chosen packs (incl. the art look)
    structured/packs/{narrative,cinematography}.yaml       vendored packs
    structured/looks/<look>/art.yaml                       vendored art pack
    structured/looks/<look>/style.yaml                     palettes and pens
    assets/<look>/...                                      frozen art for that look
"""

from __future__ import annotations

from pathlib import Path
from typing import TypeVar

from . import yamlio
from .models import (
    ArtPack,
    Brief,
    Cast,
    Character,
    CinematographyPack,
    Comic,
    Composition,
    Direction,
    NarrativePack,
    Props,
    Set,
    ShotList,
    Story,
    Style,
    SubjectProduct,
)
from .models.base import Artifact
from .project import Project

A = TypeVar("A", bound=Artifact)


class Store:
    """Reads intermediates on demand. Not cached: stages read fresh upstream output."""

    def __init__(self, project: Project, look: str | None = None):
        """`look` defaults to the art style chosen in structured/direction.yaml."""
        self.project = project
        self.look = look

    def _look(self) -> str:
        return self.look or self.direction().art.id

    # --- generic ---------------------------------------------------------------
    def path(self, model: type[Artifact], id: str | None = None) -> Path:
        if model in (NarrativePack, CinematographyPack):
            return self.project.structured_dir / "packs" / f"{model.KIND}.yaml"
        if model in (ArtPack, Style):
            return self.look_dir / f"{model.KIND}.yaml"
        return self.project.artifact_path(model.KIND, id)

    def load(self, model: type[A], id: str | None = None) -> A:
        return yamlio.read_model(self.path(model, id), model)

    def text(self, model: type[Artifact], id: str | None = None) -> str:
        return self.path(model, id).read_text(encoding="utf-8").strip()

    @property
    def look_dir(self) -> Path:
        return self.project.structured_dir / "looks" / self._look()

    # --- conveniences ----------------------------------------------------------
    def brief(self) -> Brief:
        return self.load(Brief)

    def product(self) -> SubjectProduct:
        return self.load(SubjectProduct)

    def cast(self) -> Cast:
        return self.load(Cast)

    def story(self) -> Story:
        return self.load(Story)

    def props(self) -> Props:
        return self.load(Props)

    def shotlist(self) -> ShotList:
        return self.load(ShotList)

    def comic(self) -> Comic:
        return self.load(Comic)

    def composition(self) -> Composition:
        return self.load(Composition)

    def character(self, id: str) -> Character:
        return self.load(Character, id)

    def set(self, id: str) -> Set:
        return self.load(Set, id)

    def direction(self) -> Direction:
        return self.load(Direction)

    def narrative(self) -> NarrativePack:
        return self.load(NarrativePack)

    def cinematography(self) -> CinematographyPack:
        return self.load(CinematographyPack)

    def art(self) -> ArtPack:
        return self.load(ArtPack)

    def style(self) -> Style:
        return self.load(Style)

    def character_ids(self) -> list[str]:
        return [m.id for m in self.cast().members]

    def set_ids(self) -> list[str]:
        """Sets named by the story, in first-appearance order."""
        return list(dict.fromkeys(b.set for b in self.story().beats if b.set))

    # --- assets (per look) -----------------------------------------------------
    @property
    def look_assets(self) -> Path:
        return self.project.assets_dir / self._look()

    def character_model_path(self, id: str) -> Path:
        return self.look_assets / "characters" / id / "model.svg"

    def character_pose_path(self, id: str, pose: str, expression: str) -> Path:
        return self.look_assets / "characters" / id / f"{pose}--{expression}.svg"

    def set_backdrop_path(self, id: str) -> Path:
        return self.look_assets / "sets" / f"{id}.svg"

    def prop_art_path(self, id: str) -> Path:
        return self.look_assets / "props" / f"{id}.svg"

    def font_path(self, filename: str) -> Path:
        return self.look_assets / "fonts" / filename
