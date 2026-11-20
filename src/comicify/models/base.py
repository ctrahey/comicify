"""Shared base types for all intermediate artifacts."""

from __future__ import annotations

from typing import Annotated, ClassVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# Stable, human-readable identifiers used for cross-references between
# artifacts (e.g. a panel refers to `character: hare`, `set: meadow`).
Slug = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=64),
]

HexColor = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]


class Model(BaseModel):
    """Strict base: unknown keys in hand-edited YAML are errors, not silently dropped."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class Artifact(Model):
    """A top-level intermediate written to `structured/`.

    `kind` and `schema_version` let us evolve schemas and migrate files later.
    """

    KIND: ClassVar[str]
    SCHEMA_VERSION: ClassVar[int] = 1

    schema_version: int = Field(default=1, description="Schema version of this artifact file.")


def unit(description: str, default: float | None = None):
    """A normalized 0..1 coordinate field."""
    if default is None:
        return Field(ge=0.0, le=1.0, description=description)
    return Field(default=default, ge=0.0, le=1.0, description=description)
