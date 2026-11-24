"""Editorial review: the script editor's notes, and the author's decisions on them."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from .base import Model, Slug


class Principle(StrEnum):
    SHOW_DONT_TELL = "show-dont-tell"
    ONE_IDEA = "one-idea-per-panel"
    COHERENCE = "coherence"
    SIGNALING = "signaling"
    REDUNDANCY = "redundancy"
    CONTIGUITY = "contiguity"
    SEGMENTING = "segmenting"
    PRE_TRAINING = "pre-training"
    DIALOGUE_ECONOMY = "dialogue-economy"
    STAGING = "staging"
    PACING = "pacing"


class EditKind(StrEnum):
    CUT = "cut"
    MERGE = "merge"
    SPLIT = "split"
    ADD_INSERT = "add-insert"  # show the artifact the words refer to
    REWRITE = "rewrite"  # dialogue or caption
    RESTAGE = "restage"  # camera, depth, acting
    REORDER = "reorder"


class Priority(StrEnum):
    HIGH = "high"  # readers will misunderstand or lose the thread without it
    MEDIUM = "medium"  # noticeably clearer or tighter
    LOW = "low"  # polish


class EditorialNote(Model):
    id: Slug
    principle: Principle
    kind: EditKind
    priority: Priority
    targets: list[Slug] = Field(description="Beat or panel ids the note applies to.")
    problem: str = Field(description="What's wrong, for the reader, in one or two sentences.")
    proposal: str = Field(description="The concrete change: what to cut, add, or say instead.")
    source: str = Field(default="editor", description="'editor' (model) or 'lint' (code).")


class EditorialReview(Model):
    assessment: str = Field(description="Two to four sentences: how well the comic teaches.")
    notes: list[EditorialNote] = Field(
        description="At most 10, highest priority first. Empty if nothing worth changing.")


class Decision(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    MODIFY = "modify"  # accepted with the author's own wording


class EditorialDecision(Model):
    note_id: Slug
    decision: Decision
    direction: str = Field(description="The change to apply (the proposal, or the author's).")
    note: EditorialNote
