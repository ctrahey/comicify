"""The interactive clarification loop.

    evaluate → questions → ask author → (re-evaluate with answers → ask again)*

Rounds continue until the evaluation is `ready`, the model has nothing worth
asking, the author ends the session, or `max_rounds` is reached. The whole
session is written to `sessions/<date>-NN-clarify.md`, and the author sources
are marked as consumed in the manifest.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .. import prompting, yamlio
from ..direction import catalogue
from ..llm import LLM
from ..manifest import Manifest, current_sources
from ..models import (
    AnswerSource,
    ClarificationAnswer,
    ClarifyingQuestion,
    Evaluation,
    QuestionSet,
    Readiness,
)
from ..project import Project
from ..sessions import (
    ClarifySession,
    all_answers,
    clarify_protocol,
    now_iso,
    write_clarify_session,
)
from .evaluate import evaluate, revisions


class EndSession(Exception):
    """Raised by the UI when the author wants to stop answering."""


class ClarifyUI(Protocol):
    def status(self, message: str) -> None: ...

    def show_evaluation(self, evaluation: Evaluation, round_no: int) -> None: ...

    def ask(self, question: ClarifyingQuestion, index: int, total: int) -> str | None:
        """Return the author's answer, None to skip (accept the assumption),
        or raise EndSession to stop."""
        ...


@dataclass
class ClarifyOutcome:
    session_path: Path | None
    evaluation: Evaluation
    answers: list[ClarificationAnswer]


def questions_for(
    project: Project,
    llm: LLM,
    evaluation: Evaluation,
    answers: list[ClarificationAnswer],
    max_questions: int,
) -> list[ClarifyingQuestion]:
    prompt = prompting.render(
        "clarify",
        prompt=project.read_prompt(),
        revisions=revisions(project),
        answers=answers,
        evaluation_yaml=yamlio.dumps(evaluation).strip(),
        max_questions=max_questions,
        catalogue=catalogue(project),
    )
    asked = {a.question_id for a in answers}
    qs = llm.structured(prompt, QuestionSet).output.questions
    return [q for q in qs if q.id not in asked][:max_questions]


def run(
    project: Project,
    llm: LLM,
    ui: ClarifyUI,
    *,
    max_rounds: int = 2,
    max_questions: int = 5,
) -> ClarifyOutcome:
    project.ensure_layout()
    prior = all_answers(project)
    new_answers: list[ClarificationAnswer] = []
    ended = False

    evaluation = None
    model_name = ""
    for round_no in range(1, max_rounds + 1):
        ui.status("Evaluating your prompt…" if round_no == 1 else "Re-evaluating with your answers…")
        result = evaluate(project, llm, prior + new_answers)
        evaluation, model_name = result.output, result.model
        ui.show_evaluation(evaluation, round_no)

        if evaluation.readiness == Readiness.READY and round_no > 1:
            break

        ui.status("Preparing questions…")
        questions = questions_for(project, llm, evaluation, prior + new_answers, max_questions)
        if not questions:
            break

        for i, q in enumerate(questions, 1):
            reply = None  # skipped → the question's assumption stands
            if not ended:
                try:
                    reply = ui.ask(q, i, len(questions))
                except EndSession:
                    ended = True
            new_answers.append(ClarificationAnswer(
                question_id=q.id,
                question=q.question,
                answer=reply.strip() if reply and reply.strip() else q.assumption,
                source=AnswerSource.AUTHOR if reply and reply.strip() else AnswerSource.ASSUMED,
            ))
        if ended or evaluation.readiness == Readiness.READY:
            break

    assert evaluation is not None
    session = ClarifySession(
        created=now_iso(),
        model=model_name,
        protocol=clarify_protocol(),
        sources=current_sources(project),
        evaluation=evaluation,
        answers=new_answers,
    )
    path = write_clarify_session(project, session)

    # Mark the author's sources as consumed and snapshot the prompt so the next
    # run can show the evaluator exactly what changed.
    manifest = Manifest.load(project)
    manifest.mark_sources_consumed(project)
    manifest.save(project)
    project.snapshots_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(project.prompt_path, project.snapshots_dir / "prompt.md")

    return ClarifyOutcome(path, evaluation, new_answers)
