"""Tool-written session notes in `sessions/`.

Each session is a Markdown file readable by humans, with YAML front matter
holding the structured record that downstream stages consume.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from pydantic import BaseModel, Field

from . import yamlio
from .models import AnswerSource, ClarificationAnswer, Evaluation
from .project import Project


def clarify_protocol() -> str:
    """The versions of the prompts that define what clarification resolves."""
    from .prompting import version
    return f"evaluate@v{version('evaluate')}+clarify@v{version('clarify')}"


class ClarifySession(BaseModel):
    kind: str = "clarify"
    created: str
    model: str
    protocol: str = "evaluate@v1+clarify@v1"  # sessions before this field existed
    sources: dict[str, str] = Field(description="Author source digests this session was based on.")
    evaluation: Evaluation
    answers: list[ClarificationAnswer] = Field(default_factory=list)


def write_clarify_session(project: Project, session: ClarifySession) -> Path:
    path = project.new_session_path("clarify")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yamlio.join_front_matter(session.model_dump(mode="json", exclude_none=True),
                                 _clarify_body(session)),
        encoding="utf-8",
    )
    return path


def load_clarify_sessions(project: Project) -> list[ClarifySession]:
    sessions = []
    for f in project.session_files("clarify"):
        meta, _ = yamlio.split_front_matter(f.read_text(encoding="utf-8"))
        if meta:
            sessions.append(ClarifySession.model_validate(meta))
    return sessions


def all_answers(project: Project) -> list[ClarificationAnswer]:
    """Every clarification answer to date, oldest first."""
    return [a for s in load_clarify_sessions(project) for a in s.answers]


def now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _clarify_body(s: ClarifySession) -> str:
    e = s.evaluation
    lines = [
        f"# Clarification session — {s.created[:10]}",
        "",
        f"_Model: `{s.model}` · Readiness: **{e.readiness}** · Intent: **{e.intent}**_",
        "",
        "## Understanding",
        "",
        e.summary,
        "",
        f"- **Subject product:** {e.subject_product}",
        f"- **Key message:** {e.key_message}",
        f"- **Estimated panels:** {e.estimated_panels}",
        "",
        "### Characters",
        "",
        *[f"- {c}" for c in e.characters],
        "",
        "### Beats",
        "",
        *[f"{i}. {b}" for i, b in enumerate(e.beats, 1)],
        "",
    ]
    if e.concerns:
        lines += ["### Concerns", ""]
        lines += [f"- **{c.severity}** ({c.area}) `{c.id}`: {c.description}" for c in e.concerns]
        lines.append("")
    if s.answers:
        lines += ["## Questions & answers", ""]
        for a in s.answers:
            tag = "author" if a.source == AnswerSource.AUTHOR else "assumed — skipped by author"
            lines += [f"### {a.question}", "", f"**Answer ({tag}):** {a.answer}", ""]
    return "\n".join(lines)
