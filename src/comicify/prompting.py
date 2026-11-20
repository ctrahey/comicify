"""Loading and rendering the runtime stage prompts in `comicify/prompts/`.

Each stage has a directory:

    prompts/<stage>/system.md      system prompt (front matter: `version: N`)
    prompts/<stage>/user.md.j2     user message template

Shared guidance lives in `prompts/_shared/` and is pulled in with Jinja
`{% include %}`. Controlled vocabularies (enums) are injected from the Pydantic
models so the prompts and the schemas can't drift apart.

Bumping a stage's `version` invalidates outputs produced by the old version.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import jinja2

from . import yamlio
from .manifest import digest_text
from .models import brief, cast, evaluation, product, shotlist, story

PROMPTS_DIR = Path(__file__).parent / "prompts"


def _enum_values(e: type[Enum]) -> list[str]:
    return [m.value for m in e]


VOCABULARY: dict[str, list[str]] = {
    "intents": _enum_values(brief.ComicIntent),
    "aspects": _enum_values(brief.PageAspect),
    "beat_kinds": _enum_values(story.BeatKind),
    "roles": _enum_values(cast.Role),
    "transitions": _enum_values(shotlist.Transition),
    "shots": _enum_values(shotlist.Shot),
    "text_kinds": _enum_values(shotlist.TextKind),
    "screen_elements": _enum_values(product.ScreenElementKind),
    "concern_areas": _enum_values(evaluation.Area),
    "severities": _enum_values(evaluation.Severity),
    "readiness": _enum_values(evaluation.Readiness),
}


_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(PROMPTS_DIR),
    undefined=jinja2.StrictUndefined,
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=True,
    autoescape=False,
)


@dataclass(frozen=True)
class RenderedPrompt:
    stage: str
    version: int
    system: str
    user: str

    @property
    def produced_by(self) -> str:
        return f"{self.stage}@v{self.version}"

    @property
    def digest(self) -> str:
        return digest_text(self.system + "\x00" + self.user)


def version(stage: str) -> int:
    meta, _ = yamlio.split_front_matter((PROMPTS_DIR / stage / "system.md").read_text("utf-8"))
    return int(meta.get("version", 1))


def render(stage: str, **context: Any) -> RenderedPrompt:
    stage_dir = PROMPTS_DIR / stage
    if not stage_dir.is_dir():
        raise FileNotFoundError(f"No prompts for stage {stage!r} in {PROMPTS_DIR}")

    from .fonts import REGISTRY  # local import: fonts imports nothing from here

    ctx = {"vocab": VOCABULARY, "font_families": REGISTRY.families(), **context}
    # Templates are rendered with front matter stripped.
    system = _strip_fm(_env.get_template(f"{stage}/system.md").render(**ctx))
    user = _env.get_template(f"{stage}/user.md.j2").render(**ctx)
    return RenderedPrompt(stage=stage, version=version(stage), system=system.strip(), user=user.strip())


def _strip_fm(text: str) -> str:
    return yamlio.split_front_matter(text)[1]
