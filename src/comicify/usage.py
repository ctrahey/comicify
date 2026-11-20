"""Token accounting.

Two views, both tracked in VCS:
  - `.comicify/usage.jsonl`: an append-only ledger of every LLM call (including
    clarification, retries, and cache hits), i.e. what the project has *spent*.
  - `usage` on each manifest entry: what it cost to produce that artifact, i.e.
    what *this version of the comic* cost to make.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
from collections import defaultdict
from typing import Any

from pydantic import BaseModel

from .project import Project


class Usage(BaseModel):
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cache_read_tokens: int = 0
    duration_s: float = 0.0

    @classmethod
    def from_run(cls, u: Any, duration_s: float) -> Usage:
        return cls(
            requests=u.requests,
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            reasoning_tokens=getattr(u, "output_reasoning_tokens", 0) or 0,
            cache_read_tokens=getattr(u, "cache_read_tokens", 0) or 0,
            duration_s=round(duration_s, 2),
        )

    def __add__(self, other: Usage) -> Usage:
        return Usage(**{f: getattr(self, f) + getattr(other, f)
                        for f in Usage.model_fields})

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class LedgerEntry(BaseModel):
    at: str
    stage: str
    model: str
    cached: bool
    usage: Usage  # for cache hits: the original cost, not new spend

    @property
    def spent(self) -> Usage:
        return Usage() if self.cached else self.usage


_lock = threading.Lock()


def ledger_path(project: Project):
    return project.state_dir / "usage.jsonl"


def record(project: Project, stage: str, model: str, usage: Usage, cached: bool) -> None:
    entry = LedgerEntry(at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
                        stage=stage, model=model, cached=cached, usage=usage)
    with _lock:
        project.state_dir.mkdir(parents=True, exist_ok=True)
        with ledger_path(project).open("a", encoding="utf-8") as f:
            f.write(entry.model_dump_json() + "\n")


def ledger(project: Project) -> list[LedgerEntry]:
    path = ledger_path(project)
    if not path.exists():
        return []
    return [LedgerEntry.model_validate(json.loads(line))
            for line in path.read_text("utf-8").splitlines() if line.strip()]


def cost_usd(model: str, usage: Usage) -> float | None:
    """Price a call from genai-prices' published rates; None if the model is unknown."""
    if not model or model in ("code", "test") or ":" not in model:
        return None
    provider, name = model.split(":", 1)
    try:
        from genai_prices import Usage as PriceUsage
        from genai_prices import calc_price
        price = calc_price(PriceUsage(input_tokens=usage.input_tokens,
                                      output_tokens=usage.output_tokens,
                                      cache_read_tokens=usage.cache_read_tokens or None),
                           model_ref=name, provider_id=provider)
        return float(price.total_price)
    except Exception:  # noqa: BLE001 — unknown model/provider: no price, not an error
        return None


def by_stage(items: list[tuple[str, str, Usage]]) -> dict[str, tuple[set[str], Usage]]:
    """Group (stage, model, usage) triples → {stage: (models, total usage)}."""
    out: dict[str, tuple[set[str], Usage]] = defaultdict(lambda: (set(), Usage()))
    for stage, model, u in items:
        models, total = out[stage]
        models.add(model)
        out[stage] = (models, total + u)
    return dict(out)
