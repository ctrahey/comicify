"""Rendering: compose the scene for one look, then run each backend into rendered/<look>/vN/."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from ..manifest import digest_file
from ..project import Project
from ..store import Store
from .backends import BACKENDS, FontMode
from .appendix import appendix_pages
from .colophon import colophon_page, gather
from .compose import Composer, Fidelity

RENDERER_VERSION = 2


@dataclass
class RenderResult:
    out_dir: Path
    files: list[Path]
    missing_assets: list[str]


def next_version_dir(project: Project, look: str) -> Path:
    base = project.rendered_dir / look
    base.mkdir(parents=True, exist_ok=True)
    nums = [int(m.group(1)) for d in base.iterdir() if (m := re.fullmatch(r"v(\d+)", d.name))]
    return base / f"v{max(nums, default=0) + 1}"


def render(project: Project, look: str, backends: list[str], font_mode: FontMode,
           colophon: bool = True, appendix: bool = False,
           fidelity: str = Fidelity.FINAL) -> RenderResult:
    unknown = [b for b in backends if b not in BACKENDS]
    if unknown:
        raise ValueError(f"Unknown backend(s) {unknown}; available: {sorted(BACKENDS)}")

    store = Store(project, look)
    composer = Composer(store, fidelity)
    scene = composer.compose()
    missing = sorted(set(composer.missing))
    if colophon:
        data = gather(project, look=look, title=composer.brief.title, logline=composer.brief.logline,
                      pages=len(scene.pages), panels=len(composer.panels),
                      renderer_version=RENDERER_VERSION, fonts=scene.fonts,
                      layers=[("narrative", store.narrative().name),
                              ("cinematography", store.cinematography().name),
                              ("art", store.art().name)])
        scene.pages.append(colophon_page(data, composer.theme, composer.width, composer.height,
                                         page_id="colophon"))
    if appendix:
        scene.pages += appendix_pages(project, look, composer.width, composer.height,
                                      paper="#ffffff")
        mono = {p.face for page in scene.pages for p in page.walk() if hasattr(p, "face")}
        scene.fonts = sorted(set(scene.fonts) | mono, key=lambda f: f.key)
    out = next_version_dir(project, "thumbnails" if fidelity == Fidelity.THUMBNAILS else look)
    out.mkdir(parents=True)
    files: list[Path] = []
    for name in backends:
        files += BACKENDS[name](font_mode).render(scene, out)

    # Record exactly what this render was made from, so it is reproducible.
    inputs = sorted([*project.structured_files(),
                     *(p for p in project.assets_dir.rglob("*") if p.is_file())]
                    if project.assets_dir.exists() else project.structured_files())
    (out / "render.json").write_text(json.dumps({
        "renderer_version": RENDERER_VERSION,
        "look": look,
        "fidelity": fidelity,
        "backends": backends,
        "font_mode": font_mode,
        "missing_assets": missing,
        "inputs": {project.rel(p): digest_file(p) for p in inputs},
    }, indent=2) + "\n", encoding="utf-8")
    return RenderResult(out, files, missing)
