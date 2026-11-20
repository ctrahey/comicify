"""The direction pack catalogue: what's available to choose from.

Packs are found in (later wins):
  1. built-in:  comicify/styles/<axis>/<id>.yaml
  2. project:   <project>/styles/<axis>/<id>.yaml

Which packs a comic uses is *not* configuration: it's decided during
clarification and recorded in the `structured/direction.yaml` intermediate.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import yamlio
from .models.direction import PACK_TYPES, Axis, Pack
from .project import Project

BUILTIN_DIR = Path(__file__).parent / "styles"
DEFAULTS = {Axis.NARRATIVE: "three-act", Axis.CINEMATOGRAPHY: "newspaper-strip",
            Axis.ART: "clean-cartoon"}


class DirectionError(Exception):
    pass


@dataclass(frozen=True)
class PackSource:
    axis: Axis
    id: str
    path: Path
    builtin: bool


def available(project: Project | None = None) -> dict[Axis, dict[str, PackSource]]:
    out: dict[Axis, dict[str, PackSource]] = {a: {} for a in Axis}
    roots = [(BUILTIN_DIR, True)] + ([(project.root / "styles", False)] if project else [])
    for root, builtin in roots:
        for axis in Axis:
            for f in sorted((root / axis.value).glob("*.yaml")):
                out[axis][f.stem] = PackSource(axis, f.stem, f, builtin)
    return out


def load_pack(source: PackSource) -> Pack:
    model = PACK_TYPES[source.axis]
    try:
        pack = model.model_validate(yamlio.loads(source.path.read_text("utf-8")))
    except Exception as e:
        raise DirectionError(f"Invalid {source.axis} pack {source.path}: {e}") from e
    if pack.id != source.id:
        raise DirectionError(f"{source.path}: id {pack.id!r} must match the file name")
    return pack


def catalogue(project: Project | None = None) -> list[dict]:
    """The catalogue as prompt context: per axis, each pack's id, name, and summary."""
    out = []
    for axis, packs in available(project).items():
        entries = []
        for src in packs.values():
            pack = load_pack(src)
            entry = {"id": pack.id, "name": pack.name, "summary": pack.summary.strip()}
            if suits := getattr(pack, "suits", None):
                entry["suits"] = ", ".join(suits)
            entries.append(entry)
        out.append({"axis": axis.value, "packs": entries, "default": DEFAULTS[axis]})
    return out


def resolve(project: Project, axis: Axis, pack_id: str) -> PackSource:
    packs = available(project)[axis]
    if pack_id not in packs:
        raise DirectionError(
            f"Unknown {axis} pack {pack_id!r}. Available: {', '.join(sorted(packs))}")
    return packs[pack_id]
