"""Schema rules for models the LLM produces."""

import pytest

from comicify.pipeline.look import LOOK_STAGES as ASSET_STAGES
from comicify.pipeline.generate import GENERATION_STAGES
from comicify.models import Evaluation, QuestionSet

LLM_OUTPUT_TYPES = {s.output_type for s in [*GENERATION_STAGES, *ASSET_STAGES]
                    if hasattr(s, "output_type")} | {Evaluation, QuestionSet}


def _open_maps(node, path="$"):
    """Yield paths of open-ended maps (additionalProperties that isn't `false`)."""
    if isinstance(node, dict):
        ap = node.get("additionalProperties")
        if ap is not None and ap is not False:
            yield path
        for k, v in node.items():
            yield from _open_maps(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _open_maps(v, f"{path}[{i}]")


@pytest.mark.parametrize("model", sorted(LLM_OUTPUT_TYPES, key=lambda m: m.__name__))
def test_no_open_maps_in_llm_schemas(model):
    # Constrained decoding can't express arbitrary keys; the model returns `{}`.
    assert list(_open_maps(model.model_json_schema())) == []
