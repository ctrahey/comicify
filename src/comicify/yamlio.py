"""Deterministic YAML read/write for intermediates.

Output is stable: field order follows the model definition, None values are
omitted, and long strings are written in a readable block style so diffs in
VCS stay small and legible.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString

M = TypeVar("M", bound=BaseModel)


def _yaml() -> YAML:
    y = YAML()
    y.default_flow_style = False
    y.width = 100
    y.indent(mapping=2, sequence=4, offset=2)
    y.allow_unicode = True
    return y


def _blockify(value: Any) -> Any:
    """Use literal block style for multi-line strings."""
    if isinstance(value, dict):
        return {k: _blockify(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_blockify(v) for v in value]
    if isinstance(value, str) and "\n" in value:
        return LiteralScalarString(value if value.endswith("\n") else value + "\n")
    return value


def dumps(data: BaseModel | dict | list) -> str:
    if isinstance(data, BaseModel):
        data = data.model_dump(mode="json", exclude_none=True)
    buf = io.StringIO()
    _yaml().dump(_blockify(data), buf)
    return buf.getvalue()


def loads(text: str) -> Any:
    return YAML(typ="safe").load(text)


def write_model(path: Path, model: BaseModel) -> str:
    """Write a model as YAML. Returns the text written."""
    text = dumps(model)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)  # atomic: readers never see a half-written file
    return text


def read_model(path: Path, model_type: type[M]) -> M:
    return model_type.model_validate(loads(path.read_text(encoding="utf-8")) or {})


def split_front_matter(text: str) -> tuple[dict, str]:
    """Split a markdown document with optional `---` YAML front matter."""
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            return loads(text[4:end]) or {}, text[end + 5 :]
    return {}, text


def join_front_matter(meta: dict, body: str) -> str:
    return f"---\n{dumps(meta)}---\n\n{body.lstrip()}"
