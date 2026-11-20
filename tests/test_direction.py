"""Built-in direction packs: valid, consistent, and usable by the renderer."""

import pytest

from comicify.direction import DEFAULTS, available, load_pack
from comicify.fonts import REGISTRY
from comicify.models.direction import ArtPack, Axis, CinematographyPack, NarrativePack
from comicify.models.style import TextRole

PACKS = [(axis, src) for axis, packs in available().items() for src in packs.values()]


def test_defaults_exist():
    for axis, pack_id in DEFAULTS.items():
        assert pack_id in available()[axis]


@pytest.mark.parametrize("axis,src", PACKS, ids=[f"{a}:{s.id}" for a, s in PACKS])
def test_pack_is_valid(axis, src):
    pack = load_pack(src)
    if isinstance(pack, NarrativePack):
        assert 0.9 <= sum(s.share for s in pack.slots) <= 1.1
        assert len({s.id for s in pack.slots}) == len(pack.slots)
        assert pack.panels.min <= pack.panels.max
    elif isinstance(pack, CinematographyPack):
        assert 0.9 <= sum(s.share for s in pack.shot_mix) <= 1.1
        assert 0.9 <= sum(t.share for t in pack.transitions) <= 1.1
    elif isinstance(pack, ArtPack):
        for role in TextRole:  # every lettering face must be bundled
            choice = getattr(pack.lettering, role.value)
            assert REGISTRY.has_family(choice.family), (role, choice.family)
    assert pack.sources, "every pack cites where its traits come from"


def test_catalogue_size():
    counts = {a: len(p) for a, p in available().items()}
    assert counts[Axis.NARRATIVE] >= 10 and counts[Axis.CINEMATOGRAPHY] >= 8
    assert counts[Axis.ART] >= 13
