"""Script-editor lints and act-aware layout on the fixture storyboard."""

import shutil
from pathlib import Path

import pytest

from comicify import yamlio
from comicify.models import ShotList
from comicify.models.shotlist import TextElement
from comicify.pipeline.layout import layout
from comicify.project import Project
from comicify.stages.editorial import lint
from comicify.store import Store

FIXTURE = Path(__file__).parent / "fixtures" / "tortoise-hare"


@pytest.fixture
def store(tmp_path) -> Store:
    shutil.copytree(FIXTURE, tmp_path / "comic")
    return Store(Project.locate(tmp_path / "comic"))


def test_lint_flags_unseen_referent(store):
    sl = store.shotlist()
    panel = next(p for p in sl.panels if p.shot != "insert" and p.characters)
    i = sl.panels.index(panel)
    for q in sl.panels[max(0, i - 1):i + 2]:  # nothing to see nearby
        q.props = []
        q.shot = "medium" if q.shot == "insert" else q.shot
    panel.text = [TextElement(kind="speech", text="Like this one!", speaker=panel.characters[0].character)]
    yamlio.write_model(store.path(ShotList), sl)
    notes = lint(store)
    assert any(n.principle == "show-dont-tell" and panel.id in n.targets for n in notes)


def test_layout_balances_and_titles_acts(store):
    comic = layout(store.shotlist(), store.brief(), store.cinematography(), store.story())
    counts = [len(p.slots) for p in comic.pages]
    assert max(counts) - min(counts) <= max(2, max(counts) // 2), counts  # no stub pages
    order = [s.panel for p in comic.pages for s in p.slots]
    assert order == [p.id for p in store.shotlist().panels]
