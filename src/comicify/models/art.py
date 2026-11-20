"""LLM output types for generated vector art (frozen into assets/)."""

from __future__ import annotations

from pydantic import Field

from .base import Model


class SvgArt(Model):
    svg: str = Field(description="A complete, standalone SVG document.")
    notes: str = Field(default="", description="Brief notes on drawing choices, for the record.")
