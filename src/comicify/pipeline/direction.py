"""Direction: choose the packs (LLM), then vendor them into the project (code).

    direction  → structured/direction.yaml              chosen packs + rationale
    packs      → structured/packs/{narrative,cinematography}.yaml
    look       → structured/looks/<art>/art.yaml

The choice is resolved from the author's prompt and clarification answers, so
it is part of the intermediates. Vendored packs make the comic self-contained;
a hand-edited vendored pack is pinned like any other intermediate.
"""

from __future__ import annotations

from ..direction import available, catalogue, load_pack, resolve
from ..manifest import digest_file
from ..models import ArtPack, Brief, CinematographyPack, Direction, NarrativePack
from ..models.direction import Axis
from .core import Context, Job, Output
from .llmstage import Item, LLMStage

PACK_MODELS = {Axis.NARRATIVE: NarrativePack, Axis.CINEMATOGRAPHY: CinematographyPack,
               Axis.ART: ArtPack}


def check_direction(ctx: Context, item: Item, d: Direction) -> list[str]:
    packs = available(ctx.project)
    return [f"{axis}: unknown pack {d.choice(axis).id!r}; choose one of "
            f"{sorted(packs[axis])}" for axis in Axis if d.choice(axis).id not in packs[axis]]


def direction_stage(author_inputs, author_context) -> LLMStage[Direction]:
    return LLMStage(
        name="direction", output_type=Direction,
        output=lambda ctx, _: ctx.store.path(Direction),
        inputs=lambda ctx, _: [*author_inputs(ctx), ctx.store.path(Brief)],
        context=lambda ctx, _: {**author_context(ctx), "brief": ctx.store.text(Brief),
                                "catalogue": catalogue(ctx.project)},
        check=check_direction,
    )


def _vendor_job(ctx: Context, stage: str, axis: Axis) -> Job:
    source = resolve(ctx.project, axis, ctx.store.direction().choice(axis).id)
    return Job(
        stage=stage,
        key=f"{stage}:{axis}={source.id}",
        output=ctx.store.path(PACK_MODELS[axis]),
        # The pack id and content digest are the version: choosing another pack,
        # or a pack changing upstream, re-vendors it.
        produced_by=f"{stage}@{source.id}:{(digest_file(source.path) or '')[7:15]}",
        inputs=[ctx.store.path(Direction)],
        produce=lambda: Output(load_pack(source)),
    )


class PacksStage:
    """Vendors the narrative and cinematography packs (they shape the storyboard)."""

    name = "packs"

    def jobs(self, ctx: Context) -> list[Job]:
        return [_vendor_job(ctx, self.name, Axis.NARRATIVE),
                _vendor_job(ctx, self.name, Axis.CINEMATOGRAPHY)]


class LookStage:
    """Vendors the art pack for the chosen look (it shapes only the art)."""

    name = "look"

    def jobs(self, ctx: Context) -> list[Job]:
        return [_vendor_job(ctx, self.name, Axis.ART)]
