"""A comic project on disk: paths and conventions.

    <project>/
      prompt.md          author-owned seed, never modified by the tool
      revisions/         author-written revision prompts
      sessions/          tool-written session notes (clarify, chat, review)
      structured/        intermediates — the source of truth
      assets/            frozen art
      .comicify/         manifest (tracked), snapshots (tracked), cache (ignored)
      rendered/          renderer outputs
"""

from __future__ import annotations

import datetime as dt
import fcntl
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

PROMPT_FILENAME = "prompt.md"

# Singleton artifacts and their files under structured/.
SINGLETON_FILES = {
    "brief": "brief.yaml",
    "direction": "direction.yaml",
    "product": "product.yaml",
    "story": "story.yaml",
    "cast": "cast.yaml",
    "props": "props.yaml",
    "shotlist": "shotlist.yaml",
    "comic": "comic.yaml",
    "composition": "composition.yaml",
}
# Collection artifacts: kind -> subdirectory of structured/.
COLLECTION_DIRS = {
    "character": "characters",
    "set": "sets",
}


class ProjectError(Exception):
    pass


@dataclass(frozen=True)
class Project:
    root: Path

    @classmethod
    def locate(cls, path: str | Path) -> Project:
        """Accept either a project directory or the path to its prompt.md."""
        p = Path(path).expanduser().resolve()
        if p.is_file():
            if p.name != PROMPT_FILENAME:
                raise ProjectError(f"Expected a {PROMPT_FILENAME}, got {p.name}")
            p = p.parent
        if not (p / PROMPT_FILENAME).is_file():
            raise ProjectError(f"No {PROMPT_FILENAME} found in {p}")
        return cls(p)

    # --- well-known locations -------------------------------------------------
    @property
    def prompt_path(self) -> Path:
        return self.root / PROMPT_FILENAME

    @property
    def revisions_dir(self) -> Path:
        return self.root / "revisions"

    @property
    def sessions_dir(self) -> Path:
        return self.root / "sessions"

    @property
    def structured_dir(self) -> Path:
        return self.root / "structured"

    @property
    def assets_dir(self) -> Path:
        return self.root / "assets"

    @property
    def rendered_dir(self) -> Path:
        return self.root / "rendered"

    @property
    def state_dir(self) -> Path:
        return self.root / ".comicify"

    @property
    def manifest_path(self) -> Path:
        return self.state_dir / "manifest.yaml"

    @property
    def snapshots_dir(self) -> Path:
        return self.state_dir / "snapshots"

    @property
    def cache_dir(self) -> Path:
        return self.state_dir / "cache"

    def ensure_layout(self) -> None:
        for d in (self.sessions_dir, self.structured_dir, self.state_dir):
            d.mkdir(parents=True, exist_ok=True)
        gitignore = self.state_dir / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text("cache/\n", encoding="utf-8")

    @contextmanager
    def lock(self, wait: bool = False) -> Iterator[None]:
        """Exclusive lock for anything that writes to the project.

        Prevents two comicify processes from interleaving writes to the manifest
        and the same files.
        """
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with open(self.state_dir / "lock", "w") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
            except BlockingIOError as e:
                raise ProjectError(
                    f"Another comicify process is working on {self.root}; "
                    "wait for it to finish.") from e
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    # --- artifacts -------------------------------------------------------------
    def artifact_path(self, kind: str, id: str | None = None) -> Path:
        if kind in SINGLETON_FILES:
            return self.structured_dir / SINGLETON_FILES[kind]
        if kind in COLLECTION_DIRS:
            if not id:
                raise ValueError(f"Artifact kind {kind!r} requires an id")
            return self.structured_dir / COLLECTION_DIRS[kind] / f"{id}.yaml"
        raise ValueError(f"Unknown artifact kind {kind!r}")

    def rel(self, path: Path) -> str:
        """Project-relative POSIX path, used as a stable key in the manifest."""
        return path.resolve().relative_to(self.root).as_posix()

    def structured_files(self) -> list[Path]:
        if not self.structured_dir.exists():
            return []
        return sorted(self.structured_dir.rglob("*.yaml"))

    # --- author inputs ---------------------------------------------------------
    def read_prompt(self) -> str:
        return self.prompt_path.read_text(encoding="utf-8")

    def revision_files(self) -> list[Path]:
        if not self.revisions_dir.exists():
            return []
        return sorted(self.revisions_dir.glob("*.md"))

    # --- sessions --------------------------------------------------------------
    def session_files(self, kind: str | None = None) -> list[Path]:
        if not self.sessions_dir.exists():
            return []
        files = sorted(self.sessions_dir.glob("*.md"))
        if kind:
            files = [f for f in files if f.stem.endswith(f"-{kind}")]
        return files

    def new_session_path(self, kind: str, today: dt.date | None = None) -> Path:
        today = today or dt.date.today()
        prefix = today.isoformat()
        pattern = re.compile(rf"^{prefix}-(\d+)-")
        used = [
            int(m.group(1))
            for f in self.session_files()
            if (m := pattern.match(f.name))
        ]
        n = max(used, default=0) + 1
        return self.sessions_dir / f"{prefix}-{n:02d}-{kind}.md"
