"""Sets (locations) and props (objects, including subject-product devices)."""

from __future__ import annotations

from pydantic import Field

from .base import Artifact, Model, Slug


class Set(Artifact):
    KIND = "set"

    id: Slug
    name: str
    description: str = Field(description="What the backdrop shows, for the illustrator.")
    time_of_day: str | None = None
    mood: str = Field(description="Light, weather, and feeling, in plain words.")
    horizon: float = Field(
        default=0.6, ge=0, le=1, description="Horizon height as a fraction from the top."
    )
    landmarks: list[str] = Field(
        default_factory=list,
        description="Recognizable features used for continuity, e.g. 'the big oak at the finish'.",
    )


class Prop(Model):
    id: Slug
    name: str
    description: str
    product_device: bool = Field(
        default=False, description="True if this prop *is* the subject product (shows screens)."
    )
    device: str | None = Field(
        default=None, description="Device form factor if product_device, e.g. 'watch', 'phone'."
    )
    screens: list[Slug] = Field(default_factory=list, description="Screen ids it can display.")


class Props(Artifact):
    KIND = "props"

    props: list[Prop]
