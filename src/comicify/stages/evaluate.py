"""Evaluate the author's input for coherence and sufficiency."""

from __future__ import annotations

import difflib
from dataclasses import dataclass

from .. import prompting
from ..direction import catalogue
from ..llm import LLM, CallResult
from ..models import ClarificationAnswer, Evaluation
from ..project import Project

# Intermediates shown to the evaluator in reconcile mode. Deliberately the
# high-level ones: enough to detect conflicts, not the full shot list.
RECONCILE_CONTEXT = ("brief", "direction", "product", "story", "cast")


@dataclass(frozen=True)
class Revision:
    name: str
    text: str


def revisions(project: Project) -> list[Revision]:
    return [Revision(f.name, f.read_text(encoding="utf-8")) for f in project.revision_files()]


def prompt_diff(project: Project) -> str | None:
    """Unified diff of prompt.md against the snapshot taken at the last clarification."""
    snap = project.snapshots_dir / "prompt.md"
    if not snap.exists():
        return None
    old = snap.read_text(encoding="utf-8").splitlines(keepends=True)
    new = project.read_prompt().splitlines(keepends=True)
    diff = "".join(difflib.unified_diff(old, new, "prompt.md (last clarified)", "prompt.md (now)"))
    return diff or None


def existing_intermediates(project: Project) -> dict[str, str]:
    out = {}
    for kind in RECONCILE_CONTEXT:
        p = project.artifact_path(kind)
        if p.exists():
            out[project.rel(p)] = p.read_text(encoding="utf-8").strip()
    return out


def evaluate(
    project: Project, llm: LLM, answers: list[ClarificationAnswer]
) -> CallResult[Evaluation]:
    prompt = prompting.render(
        "evaluate",
        prompt=project.read_prompt(),
        revisions=revisions(project),
        answers=answers,
        prompt_diff=prompt_diff(project),
        intermediates=existing_intermediates(project),
        catalogue=catalogue(project),
    )
    return llm.structured(prompt, Evaluation)
