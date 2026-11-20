"""Lineage and staleness tracking for intermediates and assets.

For every file the tool writes, the manifest records:
  - which stage (and prompt version) produced it, with which model
  - digests of the inputs it was generated from
  - the digest of the output at write time

From that we can tell whether a file is fresh, stale (an input changed since),
or pinned (hand-edited since the tool wrote it — never silently overwritten).

The manifest also records which author sources (prompt.md, revisions) were last
consumed by the clarification stage, so a changed prompt re-triggers it.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from . import yamlio
from .project import Project
from .usage import Usage


def digest_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def digest_text(text: str) -> str:
    return digest_bytes(text.encode("utf-8"))


def digest_file(path: Path) -> str | None:
    return digest_bytes(path.read_bytes()) if path.exists() else None


class Entry(BaseModel):
    produced_by: str = Field(description="stage@prompt-version")
    model: str
    inputs: dict[str, str] = Field(default_factory=dict)
    output_digest: str
    written_at: str
    usage: Usage | None = None


class Status(StrEnum):
    MISSING = "missing"  # tracked, but the file is gone
    FRESH = "fresh"
    STALE = "stale"  # an input changed since generation
    PINNED = "pinned"  # hand-edited since generation
    UNTRACKED = "untracked"  # exists, but the tool didn't write it


class Manifest(BaseModel):
    version: int = 1
    consumed_sources: dict[str, str] = Field(
        default_factory=dict,
        description="Author sources (prompt, revisions) as of the last clarification.",
    )
    entries: dict[str, Entry] = Field(default_factory=dict)

    # --- persistence -----------------------------------------------------------
    @classmethod
    def load(cls, project: Project) -> Manifest:
        if project.manifest_path.exists():
            return yamlio.read_model(project.manifest_path, cls)
        return cls()

    def save(self, project: Project) -> None:
        project.state_dir.mkdir(parents=True, exist_ok=True)
        # Sorted keys → stable diffs.
        self.entries = dict(sorted(self.entries.items()))
        self.consumed_sources = dict(sorted(self.consumed_sources.items()))
        yamlio.write_model(project.manifest_path, self)

    # --- recording -------------------------------------------------------------
    def record(
        self,
        project: Project,
        path: Path,
        *,
        produced_by: str,
        model: str,
        inputs: list[Path],
        usage: Usage | None = None,
    ) -> None:
        self.entries[project.rel(path)] = Entry(
            produced_by=produced_by,
            model=model,
            inputs={project.rel(p): digest_file(p) or "missing" for p in inputs},
            output_digest=digest_file(path) or "missing",
            written_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            usage=usage,
        )

    # --- querying --------------------------------------------------------------
    def status(self, project: Project, path: Path) -> Status:
        key = project.rel(path)
        entry = self.entries.get(key)
        if entry is None:
            return Status.UNTRACKED if path.exists() else Status.MISSING
        current = digest_file(path)
        if current is None:
            return Status.MISSING
        if current != entry.output_digest:
            return Status.PINNED
        for rel, recorded in entry.inputs.items():
            if digest_file(project.root / rel) != recorded:
                return Status.STALE
        return Status.FRESH

    def changed_sources(self, project: Project) -> dict[str, str]:
        """Author sources that changed (or appeared/disappeared) since last clarification.

        Returns {relative path: 'new' | 'modified' | 'removed'}.
        """
        current = current_sources(project)
        changes: dict[str, str] = {}
        for rel, d in current.items():
            if rel not in self.consumed_sources:
                changes[rel] = "new"
            elif self.consumed_sources[rel] != d:
                changes[rel] = "modified"
        for rel in self.consumed_sources:
            if rel not in current:
                changes[rel] = "removed"
        return changes

    def mark_sources_consumed(self, project: Project) -> None:
        self.consumed_sources = current_sources(project)


def current_sources(project: Project) -> dict[str, str]:
    files = [project.prompt_path, *project.revision_files()]
    return {project.rel(f): digest_file(f) for f in files if f.exists()}  # type: ignore[misc]
