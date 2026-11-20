"""The comic: panels arranged into pages. Pure layout — content lives in the shot list."""

from __future__ import annotations

from pydantic import Field

from .base import Artifact, Model, Slug


class PanelSlot(Model):
    panel: Slug
    row: int = Field(ge=0)
    col: int = Field(ge=0)
    row_span: int = Field(default=1, ge=1)
    col_span: int = Field(default=1, ge=1)


class Page(Model):
    id: Slug
    rows: int = Field(ge=1)
    cols: int = Field(ge=1)
    slots: list[PanelSlot]


class Comic(Artifact):
    KIND = "comic"

    pages: list[Page]
