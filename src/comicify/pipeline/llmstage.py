"""A declarative LLM-backed stage: prompt + inputs + output type + integrity checks."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .. import prompting
from .core import Context, Job, Output

Item = str | tuple[str, ...] | None


@dataclass
class LLMStage[T: BaseModel]:
    """One prompt directory → one output model → one file per item.

    Callables receive the context and the item (None for singleton stages):
      items:    which items exist (fan-out); None → a single job
      output:   where the item's file goes
      inputs:   files the job reads (drives staleness — keep it honest and narrow)
      context:  template variables for the prompt
      check:    integrity problems in an output (sent back to the model as a retry)
      finalize: deterministic post-processing (e.g. pin ids) before checks
      content:  what to write (default: the model itself, as YAML)
    """

    name: str
    output_type: type[T]
    output: Callable[[Context, Item], Path]
    inputs: Callable[[Context, Item], list[Path]]
    context: Callable[[Context, Item], dict[str, Any]]
    items: Callable[[Context], list[Item]] | None = None
    check: Callable[[Context, Item, T], list[str]] | None = None
    finalize: Callable[[Context, Item, T], T] | None = None
    content: Callable[[T], BaseModel | str | bytes] | None = None
    max_tokens: int = 16_000

    def jobs(self, ctx: Context) -> list[Job]:
        items = self.items(ctx) if self.items else [None]
        return [self._job(ctx, item) for item in items]

    def _job(self, ctx: Context, item: Item) -> Job:
        def finalize(out: T) -> T:
            return self.finalize(ctx, item, out) if self.finalize else out

        def produce() -> Output:
            prompt = prompting.render(self.name, item=item, **self.context(ctx, item))
            check = (lambda out: self.check(ctx, item, finalize(out))) if self.check else None
            result = ctx.require_llm().structured(
                prompt, self.output_type, check=check, max_tokens=self.max_tokens)
            out = finalize(result.output)
            return Output(self.content(out) if self.content else out, result.model, result.usage)

        key = self.name if item is None else f"{self.name}:{_item_key(item)}"
        return Job(
            stage=self.name,
            key=key,
            output=self.output(ctx, item),
            produced_by=f"{self.name}@v{prompting.version(self.name)}",
            inputs=self.inputs(ctx, item),
            produce=produce,
        )


def _item_key(item: Item) -> str:
    return "/".join(item) if isinstance(item, tuple) else str(item)
