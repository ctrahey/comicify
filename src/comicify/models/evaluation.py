"""Evaluation of the author's input, and the clarification Q&A that follows."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from .base import Model, Slug
from .brief import ComicIntent


class Readiness(StrEnum):
    READY = "ready"  # enough to generate intermediates; questions are optional polish
    NEEDS_CLARIFICATION = "needs-clarification"
    INSUFFICIENT = "insufficient"  # can't derive a coherent story; author must rework


class Severity(StrEnum):
    BLOCKER = "blocker"
    MAJOR = "major"
    MINOR = "minor"


class Area(StrEnum):
    STORY = "story"
    CHARACTERS = "characters"
    PRODUCT = "product"
    AUDIENCE = "audience"
    VISUALS = "visuals"
    SCOPE = "scope"
    CONSISTENCY = "consistency"  # conflicts between prompt and existing intermediates
    DIRECTION = "direction"  # narrative pattern, cinematography, or art style still open


class Concern(Model):
    id: Slug
    area: Area
    severity: Severity
    description: str


class Evaluation(Model):
    summary: str = Field(description="Your understanding of the comic, in 2-4 sentences.")
    readiness: Readiness
    intent: ComicIntent = Field(description="Best guess at the comic's intent.")
    intent_rationale: str
    subject_product: str = Field(description="One sentence: what the subject product is and does.")
    key_message: str = Field(description="Best guess at the single product insight to land.")
    characters: list[str] = Field(description="Characters you can identify (name: role).")
    beats: list[str] = Field(description="The beats you can identify, in order.")
    estimated_panels: int = Field(ge=1)
    direction: str = Field(
        default="",
        description="What the input decides or implies about narrative pattern, cinematography, "
                    "and art style (by catalogue id), and which of these remain open.")
    strengths: list[str] = Field(default_factory=list)
    concerns: list[Concern] = Field(default_factory=list)


class ClarifyingQuestion(Model):
    id: Slug
    question: str
    why: str = Field(description="Which concern this resolves and why it matters downstream.")
    addresses: list[Slug] = Field(default_factory=list, description="Concern ids.")
    options: list[str] = Field(
        default_factory=list, description="2-4 suggested answers, if the question allows it."
    )
    assumption: str = Field(
        description="What we will assume if the author skips this question."
    )


class QuestionSet(Model):
    questions: list[ClarifyingQuestion] = Field(
        description="Ordered most important first. Empty if nothing worth asking."
    )


class AnswerSource(StrEnum):
    AUTHOR = "author"
    ASSUMED = "assumed"  # author skipped; the question's assumption stands


class ClarificationAnswer(Model):
    question_id: Slug
    question: str
    answer: str
    source: AnswerSource
