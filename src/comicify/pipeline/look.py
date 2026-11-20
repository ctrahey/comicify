"""The art layer: per-look stages, run late and independently of the storyboard.

    look → style → fonts → character-model* → character-pose* → set-backdrop* → prop-art*

A *look* is one art pack applied to the storyboard. Every look has its own
style.yaml and assets/<look>/, so trying another art style never touches the
story, and switching back costs nothing.

Character art is a model sheet (neutral reference) plus one drawing per
(pose, expression) the shot list uses, each drawn against the reference.
"""

from __future__ import annotations

from pathlib import Path

from .. import svg, yamlio
from ..fonts import REGISTRY
from ..models import ArtPack, Brief, Character, Props, Set, Style, SubjectProduct, SvgArt
from ..models.style import TextRole
from .core import Context, Job, Output
from .direction import LookStage
from .llmstage import Item, LLMStage

FONTS_VERSION = 2


# --- style -----------------------------------------------------------------------------


def required_palettes(ctx: Context) -> list[str]:
    st = ctx.store
    return (["base", "device"] + [f"character-{c}" for c in st.character_ids()]
            + [f"set-{s}" for s in st.set_ids()])


def check_style(ctx: Context, item: Item, s: Style) -> list[str]:
    problems = []
    ids = [p.id for p in s.palettes]
    missing = [p for p in required_palettes(ctx) if p not in ids]
    if missing:
        problems.append(f"missing palettes: {missing}")
    colors = {c.name for p in s.palettes for c in p.colors}
    problems += [f"pen {pen.id}: color {pen.color!r} is not defined in any palette"
                 for pen in s.pens if pen.color not in colors]
    if "outline" not in {p.id for p in s.pens}:
        problems.append("pens must include `outline` (character and prop ink lines)")
    max_colors = ctx.store.art().color.max_colors
    if max_colors and len({c.hex.lower() for p in s.palettes for c in p.colors}) > max_colors:
        problems.append(f"this art style allows at most {max_colors} distinct colors overall")
    return problems


def _visuals(ctx: Context) -> str:
    out = []
    for cid in ctx.store.character_ids():
        c = ctx.store.character(cid)
        out.append({"id": c.id, "species": c.visual.species,
                    "colors": [pc.model_dump() for pc in c.visual.colors],
                    "accessories": c.visual.accessories})
    return yamlio.dumps(out)


def _sets(ctx: Context) -> str:
    return yamlio.dumps([ctx.store.set(s).model_dump(mode="json", include={
        "id", "description", "time_of_day", "mood"}) for s in ctx.store.set_ids()])


def _art_guidance(ctx: Context, stage: str) -> str:
    art = ctx.store.art()
    parts = [f"### Art style: {art.name}", art.summary.strip(),
             f"- Line: {art.line.weight_px}px at 1080p page height, "
             f"{'uniform' if art.line.uniform else 'varied'} weight, color {art.line.color}.",
             f"- Color: {'flat fills' if art.color.flat else 'shaded'}"
             + (f", at most {art.color.max_colors} colors" if art.color.max_colors else "")
             + (f", signature colors {', '.join(art.color.anchors)}" if art.color.anchors else "")
             + (f". {art.color.guidance}" if art.color.guidance else "."),
             f"- Shading/texture: {art.shading}",
             f"- Character abstraction: {art.abstraction}."]
    if art.svg_notes:
        parts.append(f"- In SVG: {art.svg_notes}")
    if frag := art.fragment(stage):
        parts.append(frag)
    return "\n".join(parts)


STYLE = LLMStage(
    name="style", output_type=Style, output=lambda ctx, _: ctx.store.path(Style),
    inputs=lambda ctx, _: [ctx.store.path(ArtPack), ctx.store.path(Brief),
                           *(ctx.store.path(Character, c) for c in ctx.store.character_ids()),
                           *(ctx.store.path(Set, s) for s in ctx.store.set_ids()),
                           ctx.store.path(SubjectProduct)],
    context=lambda ctx, _: {"brief": ctx.store.text(Brief), "characters": _visuals(ctx),
                            "sets": _sets(ctx), "guidance": _art_guidance(ctx, "style"),
                            "required_palettes": required_palettes(ctx),
                            "product": ctx.store.product().name},
    check=check_style,
)


# --- fonts -----------------------------------------------------------------------------


class FontsStage:
    """Copy the bundled fonts (and licenses) the art pack's lettering uses into the look."""

    name = "fonts"

    def jobs(self, ctx: Context) -> list[Job]:
        st = ctx.store
        lettering = st.art().lettering
        sources: dict[str, Path] = {}
        for role in TextRole:
            choice = getattr(lettering, role.value)
            face = REGISTRY.resolve(choice.family, choice.weight)
            sources[f"{face.path.parent.name}/{face.path.name}"] = face.path
            sources[f"{face.path.parent.name}/{face.license.name}"] = face.license
        return [Job(
            stage=self.name, key=f"fonts:{dest}", output=st.font_path(dest),
            produced_by=f"fonts@code-v{FONTS_VERSION}", inputs=[st.path(ArtPack)],
            produce=lambda src=src: Output(src.read_bytes()),
        ) for dest, src in sorted(sources.items())]


# --- drawings --------------------------------------------------------------------------


def svg_check(canvas: svg.Canvas, anchors: tuple[str, ...] = ()):
    def check(ctx: Context, item: Item, art: SvgArt) -> list[str]:
        return svg.validate(art.svg, canvas, anchors=anchors)
    return check


def clean_svg(ctx: Context, item: Item, art: SvgArt) -> SvgArt:
    return art.model_copy(update={"svg": svg.extract_svg(art.svg).strip() + "\n"})


def _svg_stage(name: str, canvas: svg.Canvas, anchors: tuple[str, ...] = (), **kw):
    return LLMStage(name=name, output_type=SvgArt, check=svg_check(canvas, anchors),
                    finalize=clean_svg, content=lambda art: art.svg, max_tokens=16_000, **kw)


def required_poses(ctx: Context) -> list[tuple[str, str, str]]:
    """(character, pose, expression) triples used by the shot list, in first-use order."""
    seen: dict[tuple[str, str, str], None] = {}
    for panel in ctx.store.shotlist().panels:
        for c in panel.characters:
            seen[(c.character, c.pose, c.expression)] = None
    return list(seen)


def _palettes(ctx: Context, *ids: str) -> str:
    style = ctx.store.style()
    return yamlio.dumps({"pens": [p.model_dump(mode="json") for p in style.pens],
                         "palettes": [p.model_dump(mode="json") for p in style.palettes
                                      if p.id in ids]})


def _figure_height(ctx: Context, cid: str) -> int:
    return round(svg.CHARACTER_CANVAS.figure_height
                 * ctx.store.character(cid).visual.relative_height)


def _art_inputs(ctx: Context) -> list[Path]:
    return [ctx.store.path(ArtPack), ctx.store.path(Style)]


CHARACTER_MODEL = _svg_stage(
    "character-model", svg.CHARACTER_CANVAS, anchors=svg.FIGURE_ANCHORS,
    items=lambda ctx: list(ctx.store.character_ids()),
    output=lambda ctx, cid: ctx.store.character_model_path(cid),
    inputs=lambda ctx, cid: [ctx.store.path(Character, cid), *_art_inputs(ctx)],
    context=lambda ctx, cid: {
        "character": ctx.store.text(Character, cid),
        "style": _palettes(ctx, "base", f"character-{cid}"),
        "guidance": _art_guidance(ctx, "character-model"),
        "canvas": svg.CHARACTER_CANVAS, "figure_height": _figure_height(ctx, cid)},
)

CHARACTER_POSE = _svg_stage(
    "character-pose", svg.CHARACTER_CANVAS, anchors=svg.FIGURE_ANCHORS,
    items=required_poses,
    output=lambda ctx, it: ctx.store.character_pose_path(*it),
    inputs=lambda ctx, it: [ctx.store.path(Character, it[0]), *_art_inputs(ctx),
                            ctx.store.character_model_path(it[0])],
    context=lambda ctx, it: {
        "character": ctx.store.text(Character, it[0]),
        "style": _palettes(ctx, "base", f"character-{it[0]}"),
        "guidance": _art_guidance(ctx, "character-pose"),
        "model_svg": ctx.store.character_model_path(it[0]).read_text("utf-8"),
        "pose": it[1], "expression": it[2], "canvas": svg.CHARACTER_CANVAS,
        "figure_height": _figure_height(ctx, it[0])},
)

SET_BACKDROP = _svg_stage(
    "set-backdrop", svg.SET_CANVAS,
    items=lambda ctx: list(ctx.store.set_ids()),
    output=lambda ctx, sid: ctx.store.set_backdrop_path(sid),
    inputs=lambda ctx, sid: [ctx.store.path(Set, sid), *_art_inputs(ctx)],
    context=lambda ctx, sid: {"set": ctx.store.text(Set, sid),
                              "style": _palettes(ctx, "base", f"set-{sid}"),
                              "guidance": _art_guidance(ctx, "set-backdrop"),
                              "canvas": svg.SET_CANVAS},
)


def _prop(ctx: Context, pid: Item) -> str:
    return yamlio.dumps(next(p for p in ctx.store.props().props if p.id == pid)).strip()


PROP_ART = _svg_stage(
    "prop-art", svg.PROP_CANVAS,
    items=lambda ctx: [p.id for p in ctx.store.props().props],
    output=lambda ctx, pid: ctx.store.prop_art_path(pid),
    inputs=lambda ctx, pid: [ctx.store.path(Props), *_art_inputs(ctx)],
    context=lambda ctx, pid: {"prop": _prop(ctx, pid), "style": _palettes(ctx, "base", "device"),
                              "guidance": _art_guidance(ctx, "prop-art"),
                              "canvas": svg.PROP_CANVAS},
)

LOOK_STAGES = [LookStage(), STYLE, FontsStage(), CHARACTER_MODEL, CHARACTER_POSE,
               SET_BACKDROP, PROP_ART]
