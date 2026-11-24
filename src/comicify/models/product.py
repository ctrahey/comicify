"""The subject product: the thing the comic is about.

This is where product-development domain awareness lives. Features carry the
rules that make them work; screens describe the (deliberately abstracted) UI
the story needs to show.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from .base import Artifact, Model, Slug


class ScreenElementKind(StrEnum):
    TEXT = "text"
    HEADLINE = "headline"
    ICON = "icon"
    BUTTON = "button"
    GAUGE = "gauge"  # progress / meter / dial
    LIST = "list"
    NOTIFICATION = "notification"
    IMAGE = "image"  # placeholder image region
    MAP = "map"
    CHART = "chart"


class Tone(StrEnum):
    NEUTRAL = "neutral"
    POSITIVE = "positive"  # approve, confirm, success (green)
    NEGATIVE = "negative"  # deny, delete, error (red)
    ACCENT = "accent"  # the product's primary action


class ScreenElement(Model):
    kind: ScreenElementKind
    label: str | None = Field(default=None, description="Short label, if any.")
    content: str | None = Field(default=None, description="Text or value shown, if any.")
    emphasis: bool = False
    tone: Tone = Field(default=Tone.NEUTRAL,
                       description="Semantic color; consecutive buttons render side by side.")


class Screen(Model):
    """A UI state of the subject product, drawn abstractly in the comic's style.

    Per Cheng: show only what the reader needs to understand the moment.
    """

    id: Slug
    device: str = Field(description="Where it's shown, e.g. 'watch face', 'phone', 'kiosk'.")
    purpose: str = Field(description="What this screen communicates in the story.")
    elements: list[ScreenElement] = Field(default_factory=list)


class FeatureRule(Model):
    id: Slug
    description: str = Field(description="Plain-language rule, e.g. when the alert fires.")
    formal: str | None = Field(
        default=None,
        description="Optional precise statement (pseudo-code or math) of the rule.",
    )


class Feature(Model):
    id: Slug
    name: str
    description: str
    rules: list[FeatureRule] = Field(default_factory=list)
    screens: list[Slug] = Field(default_factory=list, description="Screen ids this feature uses.")
    depicted_as: str | None = Field(
        default=None,
        description="How the comic should make this feature legible to readers.",
    )


class SubjectProduct(Artifact):
    KIND = "product"

    name: str
    tagline: str | None = None
    form_factor: str = Field(description="E.g. 'wearable watch app', 'web dashboard'.")
    summary: str
    features: list[Feature] = Field(default_factory=list)
    screens: list[Screen] = Field(default_factory=list)
    incidental: list[str] = Field(
        default_factory=list,
        description=(
            "Product behaviors that matter to the story but aren't the featured "
            "capability (e.g. 'shows ad notifications')."
        ),
    )
