"""Stages that generate the structured intermediates from the author's input.

Order matters: each stage reads only the outputs of earlier ones.

    brief → direction → packs → product → cast → story → character* → set* → props → shotlist → layout

Everything here is art-agnostic (the storyboard); art is a later, per-look layer
(see pipeline/look.py).

Each stage's `inputs` is deliberately narrow (see DESIGN.md, "Stages and their
context"): narrower context means better repeatability and fewer tokens.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import yamlio
from ..models import (
    Brief,
    Cast,
    Character,
    CinematographyPack,
    NarrativePack,
    Props,
    Set,
    ShotList,
    Story,
    SubjectProduct,
)
from ..models.shotlist import Angle
from ..sessions import all_answers
from ..stages.evaluate import revisions
from .core import Context
from .direction import PacksStage, direction_stage
from .composition import CompositionStage
from .layout import LayoutStage
from .llmstage import Item, LLMStage

# --- shared context helpers ------------------------------------------------------


def author_inputs(ctx: Context) -> list[Path]:
    p = ctx.project
    return [p.prompt_path, *p.revision_files(), *p.session_files("clarify")]


def author_context(ctx: Context) -> dict[str, Any]:
    return {
        "prompt": ctx.project.read_prompt(),
        "revisions": revisions(ctx.project),
        "answers": all_answers(ctx.project),
    }


def path_of(model, id_from_item: bool = False):
    def f(ctx: Context, item: Item) -> Path:
        return ctx.store.path(model, item if id_from_item else None)  # type: ignore[arg-type]
    return f


def texts(ctx: Context, *models) -> dict[str, str]:
    """YAML text of upstream singletons, keyed by kind, for prompt templates."""
    return {m.KIND: ctx.store.text(m) for m in models}


def character_paths(ctx: Context) -> list[Path]:
    return [ctx.store.path(Character, cid) for cid in ctx.store.character_ids()]


def set_paths(ctx: Context) -> list[Path]:
    return [ctx.store.path(Set, sid) for sid in ctx.store.set_ids()]


def guidance(ctx: Context, stage: str, *packs) -> str:
    """Pack-specific guidance for a stage: the pack's summary and its stage fragment."""
    parts = []
    for model in packs:
        pack = ctx.store.load(model)
        text = pack.fragment(stage)
        parts.append(f"### {model.KIND.title()}: {pack.name}\n\n{pack.summary.strip()}"
                     + (f"\n\n{text}" if text else ""))
    return "\n\n".join(parts)


def pin_id(ctx: Context, item: Item, out):
    return out.model_copy(update={"id": item})


# --- integrity checks ------------------------------------------------------------


def check_story(ctx: Context, item: Item, s: Story) -> list[str]:
    cast = set(ctx.store.character_ids())
    features = {f.id for f in ctx.store.product().features}
    problems = _dupes("beat", [b.id for b in s.beats])
    slots = [sl.id for sl in ctx.store.narrative().slots]
    used = [b.slot for b in s.beats]
    problems += [f"beat {b.id}: slot {b.slot!r} is not in the pattern ({slots})"
                 for b in s.beats if b.slot not in slots]
    missing = [sl for sl in slots if sl not in used]
    if missing:
        problems.append(f"every slot of the pattern needs at least one beat; missing: {missing}")
    order = [slots.index(x) for x in used if x in slots]
    if order != sorted(order):
        problems.append(f"beats must follow the pattern's slot order {slots}")
    for b in s.beats:
        problems += [f"beat {b.id}: unknown character {c!r} (cast: {sorted(cast)})"
                     for c in b.characters if c not in cast]
        problems += [f"beat {b.id}: unknown feature {f!r} (features: {sorted(features)})"
                     for f in b.features if f not in features]
        if not b.set:
            problems.append(f"beat {b.id}: every beat needs a set id")
    return problems


def check_props(ctx: Context, item: Item, p: Props) -> list[str]:
    screens = {s.id for s in ctx.store.product().screens}
    problems = _dupes("prop", [x.id for x in p.props])
    for prop in p.props:
        problems += [f"prop {prop.id}: unknown screen {s!r} (screens: {sorted(screens)})"
                     for s in prop.screens if s not in screens]
        if prop.product_device and not prop.device:
            problems.append(f"prop {prop.id}: product devices need a `device` form factor")
    return problems


def check_shotlist(ctx: Context, item: Item, sl: ShotList) -> list[str]:
    st = ctx.store
    beats = {b.id for b in st.story().beats}
    sets = set(st.set_ids())
    cast = set(st.character_ids())
    props = {p.id: p for p in st.props().props}
    problems = _dupes("panel", [p.id for p in sl.panels])
    cine = st.cinematography()
    pairs: dict[str, set[tuple[str, str]]] = {}
    for i, panel in enumerate(sl.panels):
        where = f"panel {panel.id}"
        for c in panel.characters:
            pairs.setdefault(c.character, set()).add((c.pose, c.expression))
        if panel.tilt_deg and panel.angle != Angle.DUTCH:
            problems.append(f"{where}: tilt_deg is only for angle 'dutch'")
        if abs(panel.tilt_deg) > cine.camera.dutch_max_deg:
            problems.append(f"{where}: tilt {panel.tilt_deg}° exceeds this cinematography's "
                            f"limit of {cine.camera.dutch_max_deg}°")
        if panel.beat not in beats:
            problems.append(f"{where}: unknown beat {panel.beat!r}")
        if panel.set not in sets:
            problems.append(f"{where}: unknown set {panel.set!r} (sets: {sorted(sets)})")
        if i > 0 and panel.transition is None:
            problems.append(f"{where}: every panel after the first needs a transition")
        for c in panel.characters:
            if c.character not in cast:
                problems.append(f"{where}: unknown character {c.character!r}")
        for pp in panel.props:
            prop = props.get(pp.prop)
            if prop is None:
                problems.append(f"{where}: unknown prop {pp.prop!r}")
            elif pp.screen and pp.screen not in prop.screens:
                problems.append(f"{where}: prop {pp.prop} cannot show screen {pp.screen!r}")
            if pp.held_by and pp.held_by not in cast:
                problems.append(f"{where}: prop held by unknown character {pp.held_by!r}")
        for t in panel.text:
            if t.speaker and t.speaker not in cast and t.speaker not in props:
                problems.append(f"{where}: unknown speaker {t.speaker!r}")
            words = len(t.text.split())
            if t.kind in SPEECH_KINDS and words > cine.lettering.max_words_per_balloon:
                problems.append(
                    f"{where}: a balloon has {words} words; this cinematography's lettering "
                    f"budget is {cine.lettering.max_words_per_balloon} per balloon — cut or split")
            missing = [w for w in t.emphasis if w.lower() not in t.text.lower()]
            if missing:
                problems.append(f"{where}: emphasis {missing} must be words from the text")
    for cid, ps in pairs.items():
        if len(ps) > MAX_POSES_PER_CHARACTER:
            problems.append(
                f"character {cid} uses {len(ps)} distinct pose+expression pairs; each one is "
                f"a separate drawing, so reuse pairs to stay within {MAX_POSES_PER_CHARACTER}")
    return problems


MAX_POSES_PER_CHARACTER = 6
SPEECH_KINDS = {"speech", "thought", "whisper", "shout"}


def _dupes(what: str, ids: list[str]) -> list[str]:
    seen, dupes = set(), set()
    for i in ids:
        (dupes if i in seen else seen).add(i)
    return [f"duplicate {what} id {d!r}" for d in sorted(dupes)]


# --- the stages ------------------------------------------------------------------

BRIEF = LLMStage(
    name="brief", output_type=Brief, output=path_of(Brief),
    inputs=lambda ctx, _: author_inputs(ctx),
    context=lambda ctx, _: author_context(ctx),
)

PRODUCT = LLMStage(
    name="product", output_type=SubjectProduct, output=path_of(SubjectProduct),
    inputs=lambda ctx, _: [*author_inputs(ctx), ctx.store.path(Brief)],
    context=lambda ctx, _: {**author_context(ctx), **texts(ctx, Brief)},
)

CAST = LLMStage(
    name="cast", output_type=Cast, output=path_of(Cast),
    inputs=lambda ctx, _: [*author_inputs(ctx), ctx.store.path(Brief)],
    context=lambda ctx, _: {**author_context(ctx), **texts(ctx, Brief)},
    check=lambda ctx, _, c: _dupes("cast member", [m.id for m in c.members]),
)

STORY = LLMStage(
    name="story", output_type=Story, output=path_of(Story),
    inputs=lambda ctx, _: [*author_inputs(ctx), *(ctx.store.path(m) for m in
                                                   (Brief, SubjectProduct, Cast, NarrativePack))],
    context=lambda ctx, _: {**author_context(ctx), **texts(ctx, Brief, SubjectProduct, Cast),
                            "pattern": ctx.store.text(NarrativePack),
                            "guidance": guidance(ctx, "story", NarrativePack)},
    check=check_story,
)


def _member(ctx: Context, cid: Item) -> str:
    member = next(m for m in ctx.store.cast().members if m.id == cid)
    return yamlio.dumps(member).strip()


CHARACTER = LLMStage(
    name="character", output_type=Character, output=path_of(Character, id_from_item=True),
    items=lambda ctx: list(ctx.store.character_ids()),
    # The character's own notes live in the author prompt; plot details do not
    # matter here, but extracting per-character notes is future work.
    inputs=lambda ctx, _: [*author_inputs(ctx), *(ctx.store.path(m) for m in (Brief, Cast))],
    context=lambda ctx, cid: {
        **author_context(ctx), **texts(ctx, Brief, Cast), "member": _member(ctx, cid)},
    finalize=pin_id,
)


def _beats_in_set(ctx: Context, sid: Item) -> str:
    beats = [b for b in ctx.store.story().beats if b.set == sid]
    return yamlio.dumps([b.model_dump(mode="json", include={"name", "summary"}) for b in beats])


SET = LLMStage(
    name="set", output_type=Set, output=path_of(Set, id_from_item=True),
    items=lambda ctx: list(ctx.store.set_ids()),
    inputs=lambda ctx, _: [ctx.store.path(m) for m in (Brief, Story)],
    context=lambda ctx, sid: {**texts(ctx, Brief), "beats": _beats_in_set(ctx, sid)},
    finalize=pin_id,
)

PROPS = LLMStage(
    name="props", output_type=Props, output=path_of(Props),
    inputs=lambda ctx, _: [ctx.store.path(m) for m in (Brief, SubjectProduct, Cast, Story)],
    context=lambda ctx, _: texts(ctx, Brief, SubjectProduct, Cast, Story),
    check=check_props,
)


def _character_vocab(ctx: Context) -> str:
    out = []
    for cid in ctx.store.character_ids():
        c = ctx.store.character(cid)
        out.append({"id": c.id, "name": c.name, "poses": c.poses, "expressions": c.expressions,
                    "relative_height": c.visual.relative_height})
    return yamlio.dumps(out)


def _sets_summary(ctx: Context) -> str:
    return yamlio.dumps([ctx.store.set(s).model_dump(mode="json", include={"id", "name",
                                                                           "description"})
                         for s in ctx.store.set_ids()])


SHOTLIST = LLMStage(
    name="shotlist", output_type=ShotList, output=path_of(ShotList),
    inputs=lambda ctx, _: [*(ctx.store.path(m) for m in (Brief, SubjectProduct, Story, Cast,
                                                          Props, NarrativePack,
                                                          CinematographyPack)),
                           *character_paths(ctx), *set_paths(ctx)],
    context=lambda ctx, _: {**texts(ctx, Brief, SubjectProduct, Story, Cast, Props),
                            "characters": _character_vocab(ctx), "sets": _sets_summary(ctx),
                            "cinematography": ctx.store.text(CinematographyPack),
                            "guidance": guidance(ctx, "shotlist", NarrativePack,
                                                 CinematographyPack),
                            "max_poses": MAX_POSES_PER_CHARACTER,
                            "max_words": ctx.store.cinematography().lettering
                            .max_words_per_balloon},
    check=check_shotlist, max_tokens=16_000,
)

DIRECTION = direction_stage(author_inputs, author_context)

GENERATION_STAGES = [BRIEF, DIRECTION, PacksStage(), PRODUCT, CAST, STORY, CHARACTER, SET, PROPS,
                     SHOTLIST, LayoutStage(), CompositionStage()]
