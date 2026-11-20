"""The shot list: every panel's full content, independent of page layout."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from .base import Artifact, Model, Slug, unit


class Transition(StrEnum):
    """McCloud's panel-to-panel transitions (from the previous panel into this one)."""

    MOMENT = "moment-to-moment"
    ACTION = "action-to-action"
    SUBJECT = "subject-to-subject"
    SCENE = "scene-to-scene"
    ASPECT = "aspect-to-aspect"
    NON_SEQUITUR = "non-sequitur"


class Shot(StrEnum):
    ESTABLISHING = "establishing"
    WIDE = "wide"
    MEDIUM = "medium"
    CLOSE_UP = "close-up"
    EXTREME_CLOSE_UP = "extreme-close-up"
    INSERT = "insert"  # e.g. a full-panel view of a device screen
    OVER_THE_SHOULDER = "over-the-shoulder"


class Angle(StrEnum):
    EYE_LEVEL = "eye-level"
    LOW = "low"  # camera looks up: power, drama
    HIGH = "high"  # camera looks down: vulnerability, overview
    DUTCH = "dutch"  # tilted horizon: unease, energy


class Stance(StrEnum):
    STANDING = "standing"
    CROUCHING = "crouching"
    SITTING = "sitting"
    LYING = "lying"


class Facing(StrEnum):
    LEFT = "left"
    RIGHT = "right"
    VIEWER = "viewer"
    AWAY = "away"


class Placement(Model):
    """Normalized position within the panel: (0,0) top-left, (1,1) bottom-right."""

    x: float = unit("Horizontal center.")
    y: float = unit("Baseline (feet / bottom of object).")
    scale: float = Field(default=1.0, gt=0, le=4, description="Relative to the shot's default.")
    depth: int = Field(default=0, description="Z-order; higher is in front.")


class CharacterInPanel(Model):
    character: Slug
    pose: Slug
    expression: Slug
    stance: Stance = Field(default=Stance.STANDING,
                           description="Body height class of the pose; staging depends on it.")
    facing: Facing = Facing.VIEWER
    placement: Placement
    action: str | None = Field(default=None, description="What they're doing, for the record.")


class PropInPanel(Model):
    prop: Slug
    screen: Slug | None = Field(default=None, description="Screen shown, if a product device.")
    held_by: Slug | None = None
    placement: Placement | None = None


class TextKind(StrEnum):
    SPEECH = "speech"
    THOUGHT = "thought"
    WHISPER = "whisper"
    SHOUT = "shout"
    CAPTION = "caption"
    SFX = "sfx"
    DEVICE = "device"  # notification / screen text in the product's UI style


class TextElement(Model):
    kind: TextKind
    text: str
    speaker: Slug | None = Field(
        default=None, description="Character or prop id; for sfx, what makes the sound.")
    order: int = Field(default=0, description="Reading order within the panel.")
    emphasis: list[str] = Field(
        default_factory=list, description="Words to stress (lettered bold), copied exactly.")
    intensity: int = Field(
        default=1, ge=1, le=3,
        description="1 = quiet/normal, 2 = loud, 3 = the loudest moment (sfx may break "
                    "the panel frame, if the cinematography allows).")


class Panel(Model):
    id: Slug
    beat: Slug
    transition: Transition | None = Field(default=None, description="None for the first panel.")
    shot: Shot
    angle: Angle = Angle.EYE_LEVEL
    tilt_deg: float = Field(default=0, ge=-30, le=30, description="Dutch tilt, if any.")
    set: Slug
    description: str = Field(description="What the reader sees, in one or two sentences.")
    characters: list[CharacterInPanel] = Field(default_factory=list)
    props: list[PropInPanel] = Field(default_factory=list)
    text: list[TextElement] = Field(default_factory=list)
    weight: int = Field(default=1, ge=1, le=3, description="Relative visual importance / size.")


class ShotList(Artifact):
    KIND = "shotlist"

    panels: list[Panel]
