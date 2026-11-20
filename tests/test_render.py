"""Deterministic rendering on real generated intermediates, for every art pack."""

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from comicify import yamlio
from comicify.direction import available
from comicify.fonts import REGISTRY
from comicify.models.direction import Axis
from comicify.pipeline.core import Context, run_stages
from comicify.pipeline.direction import LookStage
from comicify.pipeline.layout import layout
from comicify.project import Project
from comicify.render.run import render
from comicify.render.backends import FontMode
from comicify.render.text import Font, wrap
from comicify.store import Store

FIXTURE = Path(__file__).parent / "fixtures" / "tortoise-hare"
ART_PACKS = sorted(available()[Axis.ART])


@pytest.fixture
def project(tmp_path) -> Project:
    shutil.copytree(FIXTURE, tmp_path / "comic")
    return Project.locate(tmp_path / "comic")


def with_look(project: Project, art: str) -> Project:
    """Choose an art style the way an author does: in structured/direction.yaml."""
    st = Store(project)
    d = st.direction()
    yamlio.write_model(st.path(type(d)), d.model_copy(update={
        "art": d.art.model_copy(update={"id": art})}))
    run_stages(Context(project), [LookStage()])
    return project


def test_layout_fills_rows_and_keeps_order(project):
    st = Store(project)
    comic = layout(st.shotlist(), st.brief(), st.cinematography())
    order = [s.panel for p in comic.pages for s in p.slots]
    assert order == [p.id for p in st.shotlist().panels]
    for page in comic.pages:
        rows: dict[int, int] = {}
        for s in page.slots:
            rows[s.row] = rows.get(s.row, 0) + s.col_span
        assert all(v == page.cols for v in rows.values()), "rows must have no holes"


def test_wrap_respects_width():
    font = Font(REGISTRY.resolve("Comic Neue", 400), 30)
    lines = wrap("Wake me up when I can still win this race!", font, 260)
    assert len(lines) > 1 and all(font.width(l) <= 260 for l in lines)


@pytest.mark.parametrize("art", ART_PACKS)
def test_every_art_pack_renders_deterministically(project, art):
    with_look(project, art)
    a = render(project, art, ["svg"], FontMode.OUTLINE)
    b = render(project, art, ["svg"], FontMode.OUTLINE)
    assert a.missing_assets  # no art in the fixture: placeholders are drawn
    for fa, fb in zip(a.files, b.files):
        assert fa.read_bytes() == fb.read_bytes()
        ET.fromstring(fa.read_bytes())  # well-formed


@pytest.mark.parametrize("mode", list(FontMode))
def test_font_modes(project, mode):
    with_look(project, "clean-cartoon")
    for f in render(project, "clean-cartoon", ["svg"], mode).files:
        ET.fromstring(f.read_bytes())


def test_png_pdf_appendix(project):
    with_look(project, "pop-art")
    result = render(project, "pop-art", ["png", "pdf"], FontMode.OUTLINE, appendix=True)
    pngs = [f for f in result.files if f.suffix == ".png"]
    assert len(pngs) > 3  # comic pages + colophon + appendix pages
    assert all(f.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" for f in pngs)
    pdf = next(f for f in result.files if f.suffix == ".pdf")
    assert pdf.read_bytes()[:5] == b"%PDF-"
    assert result.out_dir.parent.name == "pop-art"


def test_look_comes_from_direction_intermediate(project):
    assert Store(project).look_dir.name == "sunday-funnies"
    with_look(project, "xkcd")
    assert Store(project).look_dir.name == "xkcd"
    assert Store(project).art().id == "xkcd"
