from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from comicify import prompting, yamlio
from comicify.llm import LLM, LLMConfig
from comicify.manifest import Manifest, Status
from comicify.models import Brief, ClarifyingQuestion, Evaluation
from comicify.project import Project
from comicify.sessions import all_answers
from comicify.stages import clarify

EXAMPLE = Path(__file__).parents[1] / "example-A-tortoise-hare"

EVALUATION = {
    "summary": "A retelling of the tortoise and the hare with a smartwatch wake-up feature.",
    "readiness": "needs-clarification",
    "intent": "cautionary",
    "intent_rationale": "The feature works but an ad notification undermines it.",
    "subject_product": "A race-aware watch app that wakes you when you can still win.",
    "key_message": "Interruptions like ads can defeat a well-designed critical alert.",
    "characters": ["Hare: protagonist, product user", "Tortoise: foil", "Onlookers: chorus"],
    "beats": ["Setup", "Watch intro", "Race starts", "Nap", "Tortoise leads", "Alarm",
              "Sprint", "Ad", "Tortoise wins"],
    "estimated_panels": 9,
    "concerns": [{"id": "onlookers", "area": "characters", "severity": "minor",
                  "description": "Who are the onlookers?"}],
}
QUESTIONS = {"questions": [
    {"id": "onlookers", "question": "Who are the onlookers?", "why": "Affects every wide shot.",
     "addresses": ["onlookers"], "options": ["Meadow animals", "Birds"],
     "assumption": "A small crowd of meadow animals."},
    {"id": "ad-content", "question": "What is the ad for?", "why": "Punchline.",
     "addresses": [], "options": [], "assumption": "Hare-sneakers."},
]}


def scripted_model(calls: list[str]) -> FunctionModel:
    """Returns canned structured output based on which output schema is requested."""

    def fn(messages, info: AgentInfo) -> ModelResponse:
        tool = info.output_tools[0]
        calls.append(tool.name)
        schema_props = tool.parameters_json_schema.get("properties", {})
        args = QUESTIONS if "questions" in schema_props else EVALUATION
        return ModelResponse(parts=[ToolCallPart(tool.name, args)])

    return FunctionModel(fn)


class ScriptedUI:
    def __init__(self, replies):
        self.replies = list(replies)
        self.asked: list[str] = []

    def status(self, message):
        pass

    def show_evaluation(self, evaluation, round_no):
        pass

    def ask(self, q: ClarifyingQuestion, index, total):
        self.asked.append(q.id)
        r = self.replies.pop(0)
        if r == "/done":
            raise clarify.EndSession
        return r


@pytest.fixture
def project(tmp_path) -> Project:
    (tmp_path / "comic").mkdir()
    shutil.copy(EXAMPLE / "prompt.md", tmp_path / "comic" / "prompt.md")  # author input only
    return Project.locate(tmp_path / "comic" / "prompt.md")


@pytest.fixture
def llm(project, monkeypatch):
    calls: list[str] = []
    model = scripted_model(calls)
    monkeypatch.setattr("comicify.llm._resolve", lambda name: model)
    llm = LLM(project, LLMConfig(default_model="scripted"))
    llm.calls = calls
    return llm


def test_prompts_render_with_vocabulary():
    from comicify.direction import catalogue
    p = prompting.render("clarify", prompt="p", revisions=[], answers=[],
                         evaluation_yaml="x: 1", max_questions=3, catalogue=catalogue())
    assert p.produced_by.startswith("clarify@v")
    assert "`pop-art`" in p.system  # the direction catalogue is offered
    assert "At most 3 questions" in p.system
    assert "{%" not in p.system and "version:" not in p.system
    e = prompting.render("evaluate", prompt="p", revisions=[], answers=[],
                         prompt_diff=None, intermediates={}, catalogue=catalogue())
    assert "cautionary" in e.system  # vocabulary injected from the enum


def test_clarify_session_records_answers_and_sources(project, llm):
    ui = ScriptedUI(["Meadow animals", ""])  # answer one, skip one
    outcome = clarify.run(project, llm, ui, max_rounds=1)

    assert ui.asked == ["onlookers", "ad-content"]
    answers = all_answers(project)
    assert [(a.answer, a.source) for a in answers] == [
        ("Meadow animals", "author"), ("Hare-sneakers.", "assumed")]
    text = outcome.session_path.read_text()
    assert "Who are the onlookers?" in text and "assumed" in text

    manifest = Manifest.load(project)
    assert manifest.changed_sources(project) == {}
    assert (project.snapshots_dir / "prompt.md").exists()


def test_end_session_assumes_remaining(project, llm):
    ui = ScriptedUI(["/done"])
    clarify.run(project, llm, ui, max_rounds=2)
    assert [a.source for a in all_answers(project)] == ["assumed", "assumed"]
    assert len(ui.asked) == 1


def test_prompt_change_detected_and_diffed(project, llm):
    clarify.run(project, llm, ScriptedUI(["", ""]), max_rounds=1)
    project.prompt_path.write_text(project.read_prompt() + "\nThe hare wears sunglasses.\n")
    assert Manifest.load(project).changed_sources(project) == {"prompt.md": "modified"}

    from comicify.stages.evaluate import prompt_diff
    assert "+The hare wears sunglasses." in prompt_diff(project)


def test_llm_cache_replays(project, llm):
    clarify.run(project, llm, ScriptedUI(["", ""]), max_rounds=1)
    n = len(llm.calls)
    # A second identical evaluation is served from cache; answers changed, so
    # we call evaluate directly with the same inputs as the first run.
    from comicify.stages.evaluate import evaluate
    shutil.rmtree(project.snapshots_dir)  # same prompt context as first run
    result = evaluate(project, llm, [])
    assert result.cached and len(llm.calls) == n


def test_manifest_fresh_stale_pinned(project):
    project.ensure_layout()
    brief_path = project.artifact_path("brief")
    brief = Brief(
        title="T&H", logline="l", intent="cautionary", goal="g", key_message="k",
        audience="a", context="c", tone="fun",
        length={"target_pages": 1, "max_panels": 10},
    )
    yamlio.write_model(brief_path, brief)
    m = Manifest()
    m.record(project, brief_path, produced_by="brief@v1", model="x",
             inputs=[project.prompt_path])
    m.save(project)

    m = Manifest.load(project)
    assert m.status(project, brief_path) == Status.FRESH

    project.prompt_path.write_text("changed")
    assert m.status(project, brief_path) == Status.STALE

    brief_path.write_text(brief_path.read_text() + "# my edit\n")
    assert m.status(project, brief_path) == Status.PINNED

    assert yamlio.read_model(brief_path, Brief) == brief  # round-trips


def test_usage_is_ledgered_and_attributed(project, llm):
    from comicify.usage import ledger
    clarify.run(project, llm, ScriptedUI(["", ""]), max_rounds=1)
    entries = ledger(project)
    assert [e.stage for e in entries] == ["evaluate", "clarify"]
    assert all(e.usage.requests == 1 and e.usage.input_tokens > 0 for e in entries)


def test_yaml_is_stable():
    e = Evaluation.model_validate(EVALUATION)
    assert yamlio.dumps(e) == yamlio.dumps(Evaluation.model_validate(yamlio.loads(yamlio.dumps(e))))


def test_cli_path_defaults_to_cwd(project, monkeypatch):
    from typer.testing import CliRunner
    from comicify.cli import app
    monkeypatch.chdir(project.root)
    result = CliRunner().invoke(app, ["status"])
    assert result.exit_code == 0, result.output
    assert "No clarification yet" in result.output


def test_outdated_protocol_triggers_reclarify(project, llm):
    from comicify.sessions import clarify_protocol, load_clarify_sessions
    clarify.run(project, llm, ScriptedUI(["", ""]), max_rounds=1)
    assert load_clarify_sessions(project)[-1].protocol == clarify_protocol()
    session = project.session_files("clarify")[-1]
    session.write_text(session.read_text().replace(clarify_protocol(), "evaluate@v1+clarify@v1"))
    assert load_clarify_sessions(project)[-1].protocol != clarify_protocol()
