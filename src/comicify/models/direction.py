"""Direction packs: mix-and-match style layers.

Three independent axes, each a typed, versionable pack:

  narrative       storytelling pattern  → story beats (slots), panel budget
  cinematography  framing and pacing    → shot mix, transitions, camera, page grid
  art             visual style          → line, color, lettering, panels, render effects

Packs carry *operational* fields that code enforces (beat slots, grid policy,
halftone parameters, fonts), plus prompt fragments injected into specific
stages. Built-in packs ship with Comicify; projects can add their own. The
selected packs are vendored into the project so a comic stays reproducible.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from .base import Artifact, HexColor, Model, Slug
from .brief import ComicIntent
from .cast import Abstraction
from .shotlist import Shot, Transition


class Axis(StrEnum):
    NARRATIVE = "narrative"
    CINEMATOGRAPHY = "cinematography"
    ART = "art"


class PromptFragment(Model):
    stage: str = Field(description="Pipeline stage this guidance is injected into.")
    text: str


class Pack(Artifact):
    id: Slug
    name: str
    summary: str
    sources: list[str] = Field(default_factory=list)
    prompts: list[PromptFragment] = Field(default_factory=list)

    def fragment(self, stage: str) -> str:
        return "\n\n".join(p.text.strip() for p in self.prompts if p.stage == stage)


# --- narrative -----------------------------------------------------------------------


class BeatSlot(Model):
    id: Slug
    purpose: str
    share: float = Field(gt=0, le=1, description="Typical share of the comic's panels.")


class PanelRange(Model):
    min: int = Field(ge=1)
    max: int = Field(ge=1)


class NarrativePack(Pack):
    KIND = "narrative"

    slots: list[BeatSlot] = Field(description="Ordered beat slots every story must fill.")
    panels: PanelRange
    suits: list[ComicIntent] = Field(default_factory=list)


# --- cinematography ------------------------------------------------------------------


class ShotShare(Model):
    shot: Shot
    share: float = Field(ge=0, le=1)


class TransitionShare(Model):
    transition: Transition
    share: float = Field(ge=0, le=1)


class Camera(Model):
    """Share of panels per camera angle, and the steepest allowed Dutch tilt."""

    eye_level: float = Field(default=1.0, ge=0, le=1)
    low_angle: float = Field(default=0.0, ge=0, le=1)
    high_angle: float = Field(default=0.0, ge=0, le=1)
    dutch: float = Field(default=0.0, ge=0, le=1)
    dutch_max_deg: float = Field(default=0.0, ge=0, le=30)


class GridPolicy(StrEnum):
    REGULAR = "regular"  # uniform cells; weight ignored (e.g. 9-panel grid)
    TIERS = "tiers"  # rows of panels; weight widens panels within a row
    WIDESCREEN = "widescreen"  # full-width horizontal panels stacked
    VARIED = "varied"  # weight drives size freely; key panels may span rows


class PageGrid(Model):
    policy: GridPolicy = GridPolicy.TIERS
    max_rows: int = Field(default=3, ge=1, le=4)
    max_cols: int = Field(default=4, ge=1, le=5)
    gutter_px: float = Field(default=18, ge=0, le=60, description="At 1080px page height.")


class LetteringZone(StrEnum):
    TOP_BAND = "top-band"  # balloons in a band above the figures (newspaper strips)
    EDGES = "edges"  # balloons hug the panel's top and side edges (widescreen)
    CORNERS = "corners"  # captions and balloons tucked into corners (noir, documentary)
    FREE = "free"  # balloons float near speakers anywhere with air (manga)


class FrameBreaks(StrEnum):
    NONE = "none"
    SFX = "sfx"  # sound effects may cross panel borders
    SFX_AND_CAPTIONS = "sfx-and-captions"  # ...and captions may straddle borders


class CaptionPlacement(StrEnum):
    TOP_LEFT = "top-left"  # inset box in the top-left corner
    TOP_BAR = "top-bar"  # full-width bar across the panel top
    STRADDLE = "straddle"  # box straddling the panel's top border


class LetteringFlow(Model):
    """Where lettering lives in a panel, and how much of it there is."""

    zone: LetteringZone = LetteringZone.TOP_BAND
    speakers_left_to_right: bool = Field(
        default=True, description="Stage the first speaker on the left (Western reading order).")
    max_words_per_balloon: int = Field(default=18, ge=4, le=40)
    headroom: float = Field(
        default=0.34, ge=0, le=0.6,
        description="Share of panel height kept clear of faces for lettering when needed.")
    frame_breaks: FrameBreaks = FrameBreaks.SFX
    captions: CaptionPlacement = CaptionPlacement.TOP_LEFT


class CinematographyPack(Pack):
    KIND = "cinematography"

    shot_mix: list[ShotShare]
    transitions: list[TransitionShare]
    camera: Camera = Field(default_factory=Camera)
    composition: list[str] = Field(default_factory=list, description="Composition rules.")
    pacing: str
    grid: PageGrid = Field(default_factory=PageGrid)
    lettering: LetteringFlow = Field(default_factory=LetteringFlow)


# --- art -----------------------------------------------------------------------------


class Line(Model):
    weight_px: float = Field(gt=0, le=20, description="Outline weight at 1080px page height.")
    uniform: bool = True
    color: HexColor = "#1b1b1f"


class ColorSpec(Model):
    max_colors: int | None = Field(default=None, ge=1, le=64)
    flat: bool = True
    anchors: list[HexColor] = Field(default_factory=list, description="Signature colors.")
    guidance: str = ""


class BalloonShape(StrEnum):
    ELLIPSE = "ellipse"
    ROUNDED = "rounded"
    RECT = "rect"
    NONE = "none"  # bare text with a tail line to the speaker (xkcd)


class FontChoice(Model):
    family: str
    weight: int = 400
    size: float = Field(ge=12, le=120, description="px at 1080px page height.")
    uppercase: bool = False


class TailStyle(StrEnum):
    WEDGE = "wedge"  # classic curved wedge
    STRAIGHT = "straight"  # straight, pointed wedge
    LINE = "line"  # a single stroke (xkcd, sketchnote)


class CaptionStyle(StrEnum):
    BOX = "box"  # filled box with a border
    BAR = "bar"  # solid ink bar, knocked-out text
    PLAIN = "plain"  # text only, no box


class SfxStyle(Model):
    """How sound effects are lettered: drawn into the art, not typed on top."""

    fill: str = Field(default="accent", description="Hex color, or 'accent' / 'ink'.")
    outline: HexColor | None = "#1b1b1f"  # inner outline
    outline_px: float = 4
    halo: HexColor | None = "#ffffff"  # outer outline, separating it from the art
    halo_px: float = 10
    shadow: HexColor | None = None  # offset drop shadow / extrusion
    shadow_px: float = 0
    max_rotation_deg: float = Field(default=12, ge=0, le=40)
    scale: float = Field(default=1.0, gt=0, le=3, description="Relative to the sfx font size.")


class Lettering(Model):
    dialogue: FontChoice
    caption: FontChoice
    sfx: FontChoice
    title: FontChoice
    device: FontChoice
    balloon: BalloonShape = BalloonShape.ELLIPSE
    balloon_fill: HexColor = "#ffffff"
    caption_fill: HexColor = "#fff4c2"
    stroke_px: float = 3.0
    tail: TailStyle = TailStyle.WEDGE
    caption_style: CaptionStyle = CaptionStyle.BOX
    padding_em: float = Field(default=0.6, ge=0.1, le=2, description="Balloon inner padding.")
    emphasis_weight: int = Field(default=700, description="Weight for stressed words.")
    sfx_style: SfxStyle = Field(default_factory=SfxStyle)


class PanelStyle(Model):
    border_px: float = Field(default=4, ge=0, le=20)
    corner_radius_px: float = Field(default=0, ge=0, le=40)
    paper: HexColor = "#fbf7f0"
    ink: HexColor = "#1b1b1f"


class Halftone(Model):
    """Ben-Day / screentone dots overlaid on a layer."""

    kind: Literal["halftone"] = "halftone"
    target: Literal["backdrop", "panel"] = "backdrop"
    spacing_px: float = Field(default=10, gt=1, le=60)
    radius_px: float = Field(default=2.5, gt=0, le=30)
    angle_deg: float = 45
    color: HexColor = "#1b1b1f"
    opacity: float = Field(default=0.25, ge=0, le=1)


class Grain(Model):
    """Paper texture over the whole page."""

    kind: Literal["grain"] = "grain"
    opacity: float = Field(default=0.12, ge=0, le=1)
    frequency: float = Field(default=0.8, gt=0, le=4)


class Misregister(Model):
    """Offset ink plate, as in Risograph or cheap newsprint."""

    kind: Literal["misregister"] = "misregister"
    dx_px: float = 3
    dy_px: float = 2
    color: HexColor = "#ff48b0"
    opacity: float = Field(default=0.35, ge=0, le=1)


class Monochrome(Model):
    """Desaturate panel art (manga, noir)."""

    kind: Literal["monochrome"] = "monochrome"
    tint: HexColor | None = None


class Posterize(Model):
    """Reduce tonal levels for flat, poster-like color."""

    kind: Literal["posterize"] = "posterize"
    levels: int = Field(default=4, ge=2, le=12)


class Wobble(Model):
    """Hand-drawn line tremor (turbulence displacement) on panel art."""

    kind: Literal["wobble"] = "wobble"
    scale_px: float = Field(default=3, gt=0, le=12)
    frequency: float = Field(default=0.03, gt=0, le=0.5)
    seed: int = 7


Effect = Annotated[Halftone | Grain | Misregister | Monochrome | Posterize | Wobble,
                   Field(discriminator="kind")]


class ArtPack(Pack):
    KIND = "art"

    abstraction: Abstraction = Abstraction.CARTOON
    line: Line
    color: ColorSpec = Field(default_factory=ColorSpec)
    shading: str = Field(description="Shading/texture technique, for the illustrators.")
    lettering: Lettering
    panel: PanelStyle = Field(default_factory=PanelStyle)
    effects: list[Effect] = Field(default_factory=list)
    svg_notes: str = Field(default="", description="How to approximate this style in SVG.")


# --- the comic's direction (an intermediate) -------------------------------------------


class PackChoice(Model):
    id: Slug = Field(description="Pack id from Comicify's catalogue.")
    why: str = Field(description="Why this fits the comic, citing the author's words if any.")


class Direction(Artifact):
    """The comic's directorial choices: how it's told, framed, and drawn.

    Resolved from the author's prompt and clarification answers, and part of the
    structured intermediates like everything else: to change the art style, edit
    this file (or add a revision note) and re-render.
    """

    KIND = "direction"

    narrative: PackChoice
    cinematography: PackChoice
    art: PackChoice

    def choice(self, axis: Axis) -> PackChoice:
        return getattr(self, axis.value)


PACK_TYPES: dict[Axis, type[Pack]] = {
    Axis.NARRATIVE: NarrativePack,
    Axis.CINEMATOGRAPHY: CinematographyPack,
    Axis.ART: ArtPack,
}
