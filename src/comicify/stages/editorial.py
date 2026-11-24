"""The script editor: critique the storyboard, let the author decide, apply what's accepted.

    lint (code) + review (LLM) → notes → author accepts / rejects / rewrites
    → sessions/<date>-NN-editorial.md → story and shot list regenerate with the
      accepted directions as inputs

The author stays in charge: nothing changes without a decision, and every
decision is recorded next to the clarification sessions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field

from .. import prompting, yamlio
from ..llm import LLM
from ..models.editorial import (
    Decision,
    EditKind,
    EditorialDecision,
    EditorialNote,
    EditorialReview,
    Principle,
    Priority,
)
from ..models.shotlist import Shot, TextKind
from ..project import Project
from ..sessions import now_iso
from ..store import Store

DEICTIC = re.compile(r"\b(like this( one)?|look at (this|that)|this one|here it is|see (this|that))\b",
                     re.I)
SPEECH = {TextKind.SPEECH, TextKind.SHOUT, TextKind.WHISPER, TextKind.THOUGHT}


# --- lints: rules code can check --------------------------------------------------------


def lint(store: Store) -> list[EditorialNote]:
    notes: list[EditorialNote] = []
    story, panels = store.story(), store.shotlist().panels
    scene_of = {b.id: b.scene for b in story.beats}

    prev_scene = None
    for i, p in enumerate(panels):
        scene = scene_of.get(p.beat)
        if scene != prev_scene and p.shot not in (Shot.ESTABLISHING, Shot.WIDE, Shot.INSERT):
            notes.append(EditorialNote(
                id=f"establish-{p.id}", principle=Principle.SEGMENTING, kind=EditKind.RESTAGE,
                priority=Priority.MEDIUM, targets=[p.id], source="lint",
                problem=f"Scene '{scene}' opens on a {p.shot} shot, so readers don't see where "
                        f"they are.",
                proposal=f"Open scene '{scene}' with an establishing or wide shot of the set."))
        prev_scene = scene

        for t in p.text:
            if t.kind in SPEECH and DEICTIC.search(t.text):
                near = panels[max(0, i - 1):i + 2]
                if not any(q.shot == Shot.INSERT or q.props for q in near):
                    notes.append(EditorialNote(
                        id=f"show-{p.id}", principle=Principle.SHOW_DONT_TELL,
                        kind=EditKind.ADD_INSERT, priority=Priority.HIGH, targets=[p.id],
                        source="lint",
                        problem=f"\"{t.text}\" points at something the reader never sees.",
                        proposal="Add an insert panel (or put the thing in frame) showing "
                                 "exactly what's referred to."))
                    break

        speech = [t for t in p.text if t.kind in SPEECH]
        if len(p.text) > 3 or sum(len(t.text.split()) for t in speech) > 40:
            notes.append(EditorialNote(
                id=f"crowded-{p.id}", principle=Principle.ONE_IDEA, kind=EditKind.SPLIT,
                priority=Priority.MEDIUM, targets=[p.id], source="lint",
                problem="This panel carries too many words for one moment.",
                proposal="Split it into two panels, or cut the line that restates the picture."))
    return notes


# --- review ------------------------------------------------------------------------------


def review(project: Project, llm: LLM) -> EditorialReview:
    st = Store(project)
    lints = lint(st)
    prompt = prompting.render(
        "editorial",
        brief=st.text(type(st.brief())),
        product=st.text(type(st.product())),
        story=st.text(type(st.story())),
        shotlist=_script(st),
        lints=[n.model_dump(mode="json") for n in lints],
        prior=[d.model_dump(mode="json") for d in all_decisions(project)],
    )
    result = llm.structured(prompt, EditorialReview, max_tokens=12_000).output
    seen = {tuple(n.targets) + (n.principle,) for n in result.notes}
    extra = [n for n in lints if tuple(n.targets) + (n.principle,) not in seen]
    return EditorialReview(assessment=result.assessment, notes=[*result.notes, *extra])


def _script(st: Store) -> str:
    """The shot list as a compact comic script: what the editor needs, no geometry."""
    lines = []
    for i, p in enumerate(st.shotlist().panels, 1):
        cast = ", ".join(f"{c.character} ({c.pose}, {c.plane})" for c in p.characters)
        lines.append(f"PANEL {i} [{p.id}] beat={p.beat} · {p.shot} · {p.angle} · set={p.set}")
        lines.append(f"  {p.description}")
        if cast:
            lines.append(f"  cast: {cast}")
        for pp in p.props:
            lines.append(f"  prop: {pp.prop}" + (f" showing {pp.screen}" if pp.screen else ""))
        for t in p.text:
            who = f"{t.speaker}: " if t.speaker else ""
            lines.append(f"  {t.kind.upper()} {who}\"{t.text}\"")
    return "\n".join(lines)


# --- sessions ------------------------------------------------------------------------------


class EditorialSession(BaseModel):
    kind: str = "editorial"
    created: str
    model: str
    assessment: str
    decisions: list[EditorialDecision] = Field(default_factory=list)


def all_decisions(project: Project) -> list[EditorialDecision]:
    out = []
    for f in project.session_files("editorial"):
        meta, _ = yamlio.split_front_matter(f.read_text("utf-8"))
        if meta:
            out += EditorialSession.model_validate(meta).decisions
    return out


def accepted_directions(project: Project) -> list[str]:
    """What the story and shot list must apply: every accepted (or rewritten) note."""
    return [f"[{d.note.principle}] {', '.join(d.note.targets)}: {d.direction}"
            for d in all_decisions(project) if d.decision != Decision.REJECT]


def write_session(project: Project, session: EditorialSession) -> Path:
    path = project.new_session_path("editorial")
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# Editorial review — {session.created[:10]}", "", session.assessment, ""]
    for d in session.decisions:
        n = d.note
        lines += [f"## {d.decision.upper()} · {n.priority} · {n.principle} · {', '.join(n.targets)}",
                  "", f"**Problem:** {n.problem}", "", f"**Proposal:** {n.proposal}", ""]
        if d.decision == Decision.MODIFY:
            lines += [f"**Author's direction:** {d.direction}", ""]
    path.write_text(yamlio.join_front_matter(session.model_dump(mode="json"), "\n".join(lines)),
                    encoding="utf-8")
    return path


# --- the interactive round ---------------------------------------------------------------


class EditorialUI(Protocol):
    def status(self, message: str) -> None: ...

    def show_assessment(self, review: EditorialReview) -> None: ...

    def decide(self, note: EditorialNote, index: int, total: int) -> tuple[Decision, str]: ...


@dataclass
class EditorialOutcome:
    session_path: Path | None
    accepted: int
    total: int


def run(project: Project, llm: LLM, ui: EditorialUI) -> EditorialOutcome:
    ui.status("Reviewing the script…")
    rev = review(project, llm)
    ui.show_assessment(rev)
    if not rev.notes:
        return EditorialOutcome(None, 0, 0)
    decisions = []
    for i, note in enumerate(rev.notes, 1):
        decision, direction = ui.decide(note, i, len(rev.notes))
        decisions.append(EditorialDecision(note_id=note.id, decision=decision,
                                           direction=direction or note.proposal, note=note))
    session = EditorialSession(created=now_iso(), model=llm.config.model_for("editorial"),
                               assessment=rev.assessment, decisions=decisions)
    path = write_session(project, session)
    accepted = sum(d.decision != Decision.REJECT for d in decisions)
    return EditorialOutcome(path, accepted, len(decisions))
