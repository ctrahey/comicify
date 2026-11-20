"""The Brief: what this comic is for, and the constraints it must satisfy."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from .base import Artifact, Model


class ComicIntent(StrEnum):
    """What job the comic does for the product team."""

    PITCH = "pitch"  # show the subject product succeeding at its job
    CAUTIONARY = "cautionary"  # show a failure mode / risk the team should design against
    EDGE_CASE = "edge-case"  # explore an unusual scenario and how the product behaves
    BEFORE_AFTER = "before-after"  # contrast life without vs. with the product
    EXPLAINER = "explainer"  # explain how a feature works, step by step


class PageAspect(StrEnum):
    WIDESCREEN = "16:9"  # default: presented as slides on a call
    STANDARD = "4:3"
    PORTRAIT = "portrait"  # print-style comic page
    STRIP = "strip"  # single horizontal row


class LengthGuidance(Model):
    target_pages: int = Field(ge=1, le=24, description="Intended number of pages (slides).")
    max_panels: int = Field(ge=1, le=120, description="Hard ceiling on total panels.")
    notes: str | None = Field(default=None, description="Any nuance, e.g. 'as short as practical'.")


class Brief(Artifact):
    KIND = "brief"

    title: str
    logline: str = Field(description="One sentence: who, what happens, why it matters.")
    intent: ComicIntent
    goal: str = Field(description="What the audience should understand or feel after reading.")
    key_message: str = Field(description="The single product insight the comic must land.")
    audience: str = Field(description="Who reads this comic, and what they already know.")
    context: str = Field(description="Product/team context needed to interpret the comic.")
    tone: str = Field(description="E.g. 'casual and fun', 'earnest', 'dry humor'.")
    length: LengthGuidance
    aspect: PageAspect = PageAspect.WIDESCREEN
    out_of_scope: list[str] = Field(
        default_factory=list,
        description="Things the comic should deliberately NOT show or address.",
    )
