"""The story: a beat sheet using standard dramatic structure vocabulary."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from .base import Artifact, Model, Slug


class BeatKind(StrEnum):
    SETUP = "setup"  # establish world, characters, status quo
    INCITING = "inciting"  # the event that sets the story in motion
    RISING = "rising"  # complications, escalation
    CLIMAX = "climax"  # the decisive moment
    FALLING = "falling"  # immediate consequences
    RESOLUTION = "resolution"  # new status quo / takeaway
    PUNCHLINE = "punchline"  # comedic or ironic payoff


class Act(Model):
    """A major movement of the story. Acts start on a new page with a title."""

    id: Slug
    title: str = Field(description="Short title shown at the act's start, e.g. 'A Better Way'.")
    objective: str = Field(
        description="What the reader should understand by the end of this act.")


class Scene(Model):
    """A continuous stretch in one place and time. Scenes start on a new row."""

    id: Slug
    act: Slug
    title: str
    set: Slug
    look: Slug | None = Field(
        default=None, description="Art pack id for this scene, if it differs from the comic's.")


class Beat(Model):
    id: Slug
    act: Slug = Field(default="act-1", description="Act id this beat belongs to.")
    scene: Slug = Field(default="scene-1", description="Scene id this beat belongs to.")
    slot: Slug = Field(description="The narrative pattern's beat slot this beat fills.")
    kind: BeatKind
    name: str = Field(description="Short label, e.g. 'The nap'.")
    summary: str = Field(description="What happens.")
    purpose: str = Field(description="Why this beat exists: what it does for the reader.")
    features: list[Slug] = Field(
        default_factory=list, description="Subject-product feature ids this beat demonstrates."
    )
    characters: list[Slug] = Field(default_factory=list)
    set: Slug | None = Field(default=None, description="Set id where this beat takes place.")
    panel_budget: int = Field(default=1, ge=1, le=12, description="Rough number of panels.")


class Story(Artifact):
    KIND = "story"

    logline: str
    arc: str = Field(description="One-paragraph synopsis of the whole arc.")
    takeaway: str = Field(description="The moral / product insight as the reader should feel it.")
    acts: list[Act] = Field(default_factory=list, description="In order. At least one.")
    scenes: list[Scene] = Field(default_factory=list, description="In order. At least one.")
    beats: list[Beat]

    def act_of(self, beat_id: str) -> str | None:
        return next((b.act for b in self.beats if b.id == beat_id), None)

    def scene_of(self, beat_id: str) -> str | None:
        return next((b.scene for b in self.beats if b.id == beat_id), None)
