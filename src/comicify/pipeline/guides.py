"""Per-panel composition guides: the bridge from storyboard to finished art.

Each guide is a small SVG drawn by code from the composition: silhouettes,
horizon, props, device screens, lettering zones, and the panel's shot. It is
the thumbnail a human reviews and the brief the panel-art stage draws from.
One file per panel, so changing one panel redraws only that panel.
"""

from __future__ import annotations

from ..models import Character, Composition, Props, Set, ShotList, SubjectProduct
from ..render.backends.svg import FontMode, SvgWriter
from ..render.compose import Composer, Fidelity
from ..render.scene import Scene
from .core import Context, Job, Output

VERSION = 1


class GuidesStage:
    name = "guides"

    def jobs(self, ctx: Context) -> list[Job]:
        st = ctx.store
        inputs = [st.path(Composition), st.path(ShotList), st.path(Props),
                  st.path(SubjectProduct),
                  *(st.path(Character, c) for c in st.character_ids()),
                  *(st.path(Set, s) for s in st.set_ids())]
        cache: dict[str, Composer] = {}

        def produce(panel_id: str) -> Output:
            composer = cache.setdefault("c", Composer(st, Fidelity.THUMBNAILS))
            page = composer.panel_guide(composer.panels[panel_id])
            # Text stays as <text> (not outlines): compact, and readable by the model.
            svg = SvgWriter(FontMode.SYSTEM).write(page, Scene([page], []))
            return Output(svg)

        return [Job(stage=self.name, key=f"guides:{p.id}", output=st.guide_path(p.id),
                    produced_by=f"guides@code-v{VERSION}", inputs=inputs,
                    produce=lambda pid=p.id: produce(pid))
                for p in st.shotlist().panels]
