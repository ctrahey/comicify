"""The stage framework: jobs, freshness decisions, and the runner.

A *stage* expands into *jobs*; each job writes exactly one file from declared
input files. Before running, every job is checked against the manifest:

    missing output                → run
    output not written by us      → skip (author-owned), unless forced
    output hand-edited since       → skip (pinned), unless forced
    stage version changed          → run
    any input digest changed       → run
    otherwise                      → skip (fresh)

Stages run in order (later stages expand their jobs from earlier outputs);
jobs within a stage are independent and run concurrently.
"""

from __future__ import annotations

import concurrent.futures as cf
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from .. import yamlio
from ..llm import LLM
from ..manifest import Manifest, digest_file
from ..project import Project
from ..store import Store
from ..usage import Usage


@dataclass
class Context:
    project: Project
    llm: LLM | None = None
    force: frozenset[str] = frozenset()
    workers: int = 4
    look: str | None = None  # defaults to the art style in structured/direction.yaml
    only: frozenset[str] | None = None  # restrict per-panel stages to these panels (proofs)

    @property
    def store(self) -> Store:
        return Store(self.project, self.look)

    def require_llm(self) -> LLM:
        if self.llm is None:
            raise RuntimeError("This stage needs an LLM but none is configured")
        return self.llm


@dataclass(frozen=True)
class Output:
    content: BaseModel | str | bytes
    model: str = "code"
    usage: Usage | None = None


@dataclass
class Job:
    stage: str
    key: str
    output: Path
    produced_by: str
    inputs: list[Path]
    produce: Callable[[], Output]


class Stage(Protocol):
    name: str

    def jobs(self, ctx: Context) -> list[Job]: ...


class Action(StrEnum):
    RUN = "run"
    FRESH = "fresh"
    PINNED = "pinned"
    UNTRACKED = "untracked"


@dataclass(frozen=True)
class Decision:
    action: Action
    reason: str


def decide(ctx: Context, manifest: Manifest, job: Job) -> Decision:
    forced = job.stage in ctx.force
    if not job.output.exists():
        return Decision(Action.RUN, "missing")
    entry = manifest.entries.get(ctx.project.rel(job.output))
    if entry is None:
        return Decision(Action.RUN, "forced") if forced else Decision(
            Action.UNTRACKED, "not written by comicify; leaving it alone")
    if digest_file(job.output) != entry.output_digest:
        return Decision(Action.RUN, "forced (discarding hand edits)") if forced else Decision(
            Action.PINNED, "hand-edited; leaving it alone")
    if forced:
        return Decision(Action.RUN, "forced")
    if entry.produced_by != job.produced_by:
        return Decision(Action.RUN, f"{entry.produced_by} → {job.produced_by}")
    current = {ctx.project.rel(p): digest_file(p) or "missing" for p in job.inputs}
    changed = sorted(k for k in current.keys() | entry.inputs.keys()
                     if current.get(k) != entry.inputs.get(k))
    if changed:
        return Decision(Action.RUN, "inputs changed: " + ", ".join(changed))
    return Decision(Action.FRESH, "up to date")


def write_output(path: Path, content: BaseModel | str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, BaseModel):
        yamlio.write_model(path, content)
    elif isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_bytes(content)


class Reporter(Protocol):
    def stage_started(self, stage: str, jobs: int) -> None: ...

    def job_started(self, job: Job, decision: Decision) -> None: ...

    def job_finished(self, job: Job, decision: Decision, error: BaseException | None) -> None: ...

    def stage_finished(self, stage: str) -> None: ...


class NullReporter:
    def stage_started(self, stage, jobs): pass
    def job_started(self, job, decision): pass
    def job_finished(self, job, decision, error): pass
    def stage_finished(self, stage): pass


@dataclass
class StageFailed(Exception):
    stage: str
    failures: list[tuple[Job, BaseException]] = field(default_factory=list)

    def __str__(self) -> str:
        lines = [f"Stage {self.stage!r} failed:"]
        lines += [f"  {job.key}: {type(e).__name__}: {e}" for job, e in self.failures]
        return "\n".join(lines)


def run_stages(
    ctx: Context, stages: Sequence[Stage], reporter: Reporter | None = None
) -> dict[Action, int]:
    reporter = reporter or NullReporter()
    manifest = Manifest.load(ctx.project)
    counts = dict.fromkeys(Action, 0)

    for stage in stages:
        jobs = stage.jobs(ctx)
        _check_unique_outputs(stage.name, jobs)
        reporter.stage_started(stage.name, len(jobs))
        planned = [(job, decide(ctx, manifest, job)) for job in jobs]
        for job, d in planned:
            if d.action != Action.RUN:
                counts[d.action] += 1
                reporter.job_finished(job, d, None)

        to_run = [(job, d) for job, d in planned if d.action == Action.RUN]
        failures: list[tuple[Job, BaseException]] = []
        with cf.ThreadPoolExecutor(max_workers=max(1, ctx.workers)) as pool:
            futures = {}
            for job, d in to_run:
                reporter.job_started(job, d)
                futures[pool.submit(job.produce)] = (job, d)
            for fut in cf.as_completed(futures):
                job, d = futures[fut]
                try:
                    out = fut.result()
                except Exception as e:  # noqa: BLE001 — reported, stage fails below
                    failures.append((job, e))
                    reporter.job_finished(job, d, e)
                    continue
                # Writes and manifest updates happen on this thread only.
                write_output(job.output, out.content)
                manifest.record(ctx.project, job.output, produced_by=job.produced_by,
                                model=out.model, inputs=job.inputs, usage=out.usage)
                manifest.save(ctx.project)
                counts[Action.RUN] += 1
                reporter.job_finished(job, d, None)

        reporter.stage_finished(stage.name)
        if failures:
            raise StageFailed(stage.name, failures)
    return counts


def _check_unique_outputs(stage: str, jobs: Iterable[Job]) -> None:
    seen: set[Path] = set()
    for job in jobs:
        if job.output in seen:
            raise ValueError(f"Stage {stage!r} has two jobs writing {job.output}")
        seen.add(job.output)
