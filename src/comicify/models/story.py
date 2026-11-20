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


class Beat(Model):
    id: Slug
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
    beats: list[Beat]
