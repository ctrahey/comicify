"""Provider-agnostic structured LLM calls.

Models are named with Pydantic AI's `provider:model` strings (e.g.
`anthropic:<model>`, `openai:<model>`, `google-gla:<model>`, `ollama:<model>`).
Configuration, highest precedence first:

  1. `--model` on the command line (applies to every stage)
  2. `<project>/comicify.toml`  →  [llm.stages] <stage> = "..."
  3. `<project>/comicify.toml`  →  [llm] model = "..."
  4. env `COMICIFY_MODEL`

The special model name `test` uses Pydantic AI's TestModel (schema-valid
placeholder output, no network) for offline smoke runs.

Every call is cached under `.comicify/cache/` keyed by (model, prompts, output
schema, settings). Re-running an unchanged stage replays the same output, which
is the cheapest form of determinism we can get from an LLM.
"""

from __future__ import annotations

import json
import os
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel
from pydantic_ai import Agent, ModelRetry
from pydantic_ai.models import Model as PAIModel
from pydantic_ai.models.test import TestModel

from .manifest import digest_text
from .project import Project
from .prompting import RenderedPrompt
from .usage import Usage, record

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

T = TypeVar("T", bound=BaseModel)

CONFIG_FILENAME = "comicify.toml"


class LLMConfigError(Exception):
    pass


@dataclass
class LLMConfig:
    default_model: str | None = None
    stage_models: dict[str, str] = field(default_factory=dict)
    temperature: float | None = None  # provider default; some models reject it
    override: str | None = None
    use_cache: bool = True

    @classmethod
    def load(cls, project: Project, *, override: str | None = None, use_cache: bool = True):
        cfg = cls(override=override, use_cache=use_cache)
        user = load_user_config()
        cfg._apply(user.get("llm", {}))
        if env_model := os.environ.get("COMICIFY_MODEL"):
            cfg.default_model = env_model
        path = project.root / CONFIG_FILENAME
        if path.exists():
            cfg._apply(tomllib.loads(path.read_text(encoding="utf-8")).get("llm", {}))
        return cfg

    def _apply(self, data: dict) -> None:
        self.default_model = data.get("model", self.default_model)
        self.stage_models.update(data.get("stages", {}))
        if "temperature" in data:
            t = data["temperature"]
            self.temperature = None if t in ("none", "default") else float(t)

    def model_for(self, stage: str) -> str:
        name = self.override or self.stage_models.get(stage) or self.default_model
        if not name:
            raise LLMConfigError(
                "No model configured. Pass --model provider:model, set COMICIFY_MODEL, "
                f"or add `[llm] model = \"provider:model\"` to {CONFIG_FILENAME} in the "
                "project directory. Use `--model test` for an offline smoke run."
            )
        return name


def user_config_path() -> Path:
    if p := os.environ.get("COMICIFY_CONFIG"):
        return Path(p).expanduser()
    base = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser()
    return base / "comicify" / "config.toml"


def load_user_config() -> dict:
    """User-level config (never in a repo). Also exports secrets referenced by file:

        [env_files]
        ANTHROPIC_API_KEY = "~/path/to/key.txt"

    Each file's contents (stripped) become the env var, unless it is already set.
    """
    path = user_config_path()
    if not path.exists():
        return {}
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    for var, file in data.get("env_files", {}).items():
        if var not in os.environ:
            secret = Path(file).expanduser()
            if not secret.is_file():
                raise LLMConfigError(f"{path}: env_files.{var} points to missing file {secret}")
            os.environ[var] = secret.read_text(encoding="utf-8").strip()
    return data


def _resolve(name: str) -> PAIModel | str:
    return TestModel() if name == "test" else name


@dataclass(frozen=True)
class CallResult[T]:
    output: T
    model: str
    cached: bool
    usage: Usage  # cost of producing this output (the original cost, for cache hits)


class LLM:
    def __init__(self, project: Project, config: LLMConfig):
        self.project = project
        self.config = config

    def structured(
        self,
        prompt: RenderedPrompt,
        output_type: type[T],
        *,
        check: Callable[[T], list[str]] | None = None,
        max_tokens: int = 8_000,
    ) -> CallResult[T]:
        """Run one structured inference.

        `check` returns integrity problems (e.g. dangling cross-references); any
        problems are sent back to the model as a retry, so outputs that reach disk
        are both schema-valid and referentially valid.
        """
        model_name = self.config.model_for(prompt.stage)
        key = digest_text(json.dumps({
            "model": model_name,
            "system": prompt.system,
            "user": prompt.user,
            "schema": output_type.model_json_schema(),
            "temperature": self.config.temperature,
        }, sort_keys=True)).removeprefix("sha256:")
        cache_path = self.project.cache_dir / prompt.stage / f"{key}.json"

        if self.config.use_cache and model_name != "test" and cache_path.exists():
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            if "output" not in data:  # pre-usage cache format
                data = {"output": data, "usage": {}}
            output = output_type.model_validate(data["output"])
            if not (check and check(output)):
                usage = Usage.model_validate(data["usage"])
                record(self.project, prompt.stage, model_name, usage, cached=True)
                return CallResult(output, model_name, cached=True, usage=usage)

        settings: dict = {"max_tokens": max_tokens}
        if self.config.temperature is not None:
            settings["temperature"] = self.config.temperature
        agent = Agent(
            _resolve(model_name),
            output_type=output_type,
            instructions=prompt.system,
            model_settings=settings,
            retries=3,
        )
        if check is not None:
            @agent.output_validator
            def _integrity(output: T) -> T:
                problems = check(output)
                if problems:
                    raise ModelRetry(
                        "The output is schema-valid but has these problems; fix them all:\n"
                        + "\n".join(f"- {p}" for p in problems)
                    )
                return output

        started = time.monotonic()
        result = agent.run_sync(prompt.user)
        output = result.output
        usage = Usage.from_run(result.usage, time.monotonic() - started)
        record(self.project, prompt.stage, model_name, usage, cached=False)

        if model_name != "test":
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({
                "output": output.model_dump(mode="json"),
                "usage": usage.model_dump(),
            }, indent=2), encoding="utf-8")
        return CallResult(output, model_name, cached=False, usage=usage)


def write_config_template(path: Path) -> None:
    path.write_text(
        '[llm]\n'
        '# Any Pydantic AI model string: "anthropic:...", "openai:...", "google-gla:...", ...\n'
        '# model = "provider:model-name"\n'
        '# temperature = 0.0  # omit for provider default (some models reject it)\n\n'
        '[llm.stages]\n'
        '# Per-stage overrides, e.g.:\n'
        '# clarify = "provider:smaller-model"\n',
        encoding="utf-8",
    )
