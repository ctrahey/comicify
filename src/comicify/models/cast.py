"""The cast index and per-character profiles."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from .base import Artifact, Model, Slug


class Role(StrEnum):
    PROTAGONIST = "protagonist"
    ANTAGONIST = "antagonist"
    FOIL = "foil"
    SUPPORTING = "supporting"
    CHORUS = "chorus"  # onlookers, crowds, background reactions
    NARRATOR = "narrator"


class CastMember(Model):
    id: Slug
    name: str
    role: Role
    product_user: bool = Field(description="Does this character use the subject product?")
    summary: str
    is_group: bool = Field(default=False, description="True for crowds/onlookers.")


class Cast(Artifact):
    KIND = "cast"

    members: list[CastMember]


class Abstraction(StrEnum):
    """How iconic vs. detailed the character is drawn (McCloud's picture plane)."""

    ICONIC = "iconic"  # stick-figure-adjacent; maximal reader identification
    CARTOON = "cartoon"  # simple shapes, clear features
    DETAILED = "detailed"


class Voice(Model):
    style: str = Field(description="How they talk.")
    sample_lines: list[str] = Field(default_factory=list)


class PartColor(Model):
    part: str = Field(description="Body or costume part, e.g. 'fur', 'shell', 'sneakers'.")
    color: str = Field(description="Plain-language color, e.g. 'warm tan', 'bright red'.")


class Visual(Model):
    """Everything a renderer needs to draw this character consistently."""

    species: str = Field(description="E.g. 'hare', 'human', 'robot'.")
    abstraction: Abstraction = Abstraction.CARTOON
    relative_height: float = Field(
        gt=0, le=1.0,
        description="Standing height relative to the tallest character in the cast (tallest = 1.0).",
    )
    silhouette: str = Field(description="Overall shape readers recognize at a glance.")
    width_ratio: float = Field(
        default=0.6, gt=0.1, le=3.0,
        description="Standing silhouette width ÷ height (a person ≈ 0.4, a tortoise ≈ 1.6).")
    proportions: str = Field(description="E.g. 'big head, 3 heads tall, long ears'.")
    colors: list[PartColor] = Field(description="Color of each body/costume part.")
    distinguishing_features: list[str] = Field(default_factory=list)
    costume: str | None = None
    accessories: list[str] = Field(
        default_factory=list, description="Persistent items, may reference prop ids."
    )


class Character(Artifact):
    KIND = "character"

    id: Slug
    name: str
    personality: list[str]
    motivation: str
    voice: Voice
    visual: Visual
    expressions: list[Slug] = Field(
        default_factory=list, description="Expression vocabulary, e.g. smug, sleeping, panicked."
    )
    poses: list[Slug] = Field(
        default_factory=list, description="Pose vocabulary, e.g. standing, sprinting, napping."
    )
