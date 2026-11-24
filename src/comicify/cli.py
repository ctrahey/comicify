"""The `comicify` command line."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from .direction import available
from .models.direction import Axis
from .pipeline.look import LOOK_STAGES
from .pipeline.core import Action, Context, Decision, Job, StageFailed, run_stages
from .pipeline.generate import GENERATION_STAGES
from .render.run import render as render_comic
from .render.backends import BACKENDS, FontMode
from .llm import CONFIG_FILENAME, LLM, LLMConfig, LLMConfigError, write_config_template
from .manifest import Manifest, Status
from .models import ClarifyingQuestion, Evaluation, Readiness
from .project import Project, ProjectError
from .sessions import clarify_protocol, load_clarify_sessions
from .stages import clarify

app = typer.Typer(
    help="Turn product ideas into product comics, via VCS-tracked structured intermediates.",
    no_args_is_help=True,
)
console = Console()

ProjectArg = Annotated[Path, typer.Argument(
    help="Comic project directory or its prompt.md (default: the current directory).")]
ModelOpt = Annotated[
    str | None,
    typer.Option("--model", "-m", help="provider:model for all stages (or 'test' for offline)."),
]


def _project(path: Path) -> Project:
    try:
        return Project.locate(path)
    except ProjectError as e:
        console.print(f"[red]{escape(str(e))}[/red]")
        raise typer.Exit(2) from e


def _locked(project: Project):
    """Hold the project lock for the rest of the command."""
    import atexit
    cm = project.lock()
    try:
        cm.__enter__()
    except ProjectError as e:
        console.print(f"[red]{escape(str(e))}[/red]")
        raise typer.Exit(2) from e
    atexit.register(cm.__exit__, None, None, None)


def _show_direction(project: Project) -> None:
    from .store import Store
    d = Store(project).direction()
    console.print("[dim]direction (structured/direction.yaml): " + ", ".join(
        f"{a}={d.choice(a).id}" for a in Axis) + "[/dim]")


def _llm(project: Project, model: str | None, no_cache: bool) -> LLM:
    try:
        cfg = LLMConfig.load(project, override=model, use_cache=not no_cache)
        cfg.model_for("brief")
    except LLMConfigError as e:
        console.print(f"[red]{escape(str(e))}[/red]")
        raise typer.Exit(2) from e
    return LLM(project, cfg)


class RichReporter:
    """Prints what each stage does; the main thread is the only caller."""

    def stage_started(self, stage: str, jobs: int) -> None:
        console.print(f"[bold]{stage}[/bold] [dim]({jobs} job{'s' if jobs != 1 else ''})[/dim]")

    def job_started(self, job: Job, decision: Decision) -> None:
        console.print(f"  [cyan]…[/cyan] {escape(job.key)} [dim]{escape(decision.reason)}[/dim]")

    def job_finished(self, job: Job, decision: Decision, error: BaseException | None) -> None:
        if error is not None:
            console.print(f"  [red]✗[/red] {escape(job.key)}: {escape(str(error))[:300]}")
        elif decision.action == Action.RUN:
            console.print(f"  [green]✓[/green] {escape(job.key)}")
        elif decision.action in (Action.PINNED, Action.UNTRACKED):
            console.print(f"  [magenta]•[/magenta] {escape(job.key)} "
                          f"[magenta]{escape(decision.reason)}[/magenta]")

    def stage_finished(self, stage: str) -> None:
        pass


def _run(ctx: Context, stages) -> None:
    try:
        counts = run_stages(ctx, stages, RichReporter())
    except StageFailed as e:
        console.print(f"[red]{escape(str(e))}[/red]")
        raise typer.Exit(1) from e
    console.print(f"[dim]{counts[Action.RUN]} written, {counts[Action.FRESH]} up to date, "
                  f"{counts[Action.PINNED] + counts[Action.UNTRACKED]} left alone[/dim]")


def _force(values: list[str] | None) -> frozenset[str]:
    return frozenset(v.strip() for item in values or [] for v in item.split(",") if v.strip())


ForceOpt = Annotated[
    list[str] | None,
    typer.Option("--force", help="Stage name(s) to regenerate even if fresh or hand-edited."),
]


class AcceptDefaultsUI:
    """Non-interactive clarification: every question takes its stated assumption."""

    def status(self, message: str) -> None:
        console.print(f"[dim]… {escape(message)}[/dim]")

    def show_evaluation(self, e: Evaluation, round_no: int) -> None:
        RichClarifyUI().show_evaluation(e, round_no)

    def ask(self, q: ClarifyingQuestion, index: int, total: int) -> str | None:
        console.print(f"[cyan]Q{index}/{total}[/cyan] {escape(q.question)}\n"
                      f"   [dim]assuming: {escape(q.assumption)}[/dim]")
        return None


class RichEditorialUI:
    PRIORITY = {"high": "bold red", "medium": "yellow", "low": "dim"}

    def status(self, message: str) -> None:
        console.print(f"[dim]… {escape(message)}[/dim]")

    def show_assessment(self, review) -> None:
        console.print(Panel(escape(review.assessment),
                            title=f"Script editor · {len(review.notes)} notes", expand=False))

    def decide(self, note, index: int, total: int):
        from .models.editorial import Decision
        style = self.PRIORITY.get(str(note.priority), "")
        console.print()
        console.print(f"[bold cyan]Note {index}/{total}[/bold cyan] [{style}]{note.priority}"
                      f"[/{style}] · {note.principle} · {note.kind} · "
                      f"[dim]{escape(', '.join(note.targets))}[/dim]"
                      + (" [dim](automated check)[/dim]" if note.source == "lint" else ""))
        console.print(f"[bold]Problem:[/bold] {escape(note.problem)}")
        console.print(f"[bold]Proposal:[/bold] {escape(note.proposal)}")
        reply = Prompt.ask("[cyan]Enter = accept · n = reject · or type your own direction[/cyan]",
                           default="", show_default=False).strip()
        if reply.lower() in ("n", "no", "reject"):
            return Decision.REJECT, ""
        if reply:
            return Decision.MODIFY, reply
        return Decision.ACCEPT, ""


class AcceptEditorialUI(RichEditorialUI):
    """Non-interactive: accept high and medium priority notes, reject polish."""

    def decide(self, note, index: int, total: int):
        from .models.editorial import Decision
        ok = str(note.priority) in ("high", "medium")
        console.print(f"[cyan]Note {index}/{total}[/cyan] {'accept' if ok else 'reject'}: "
                      f"{escape(note.proposal)}")
        return (Decision.ACCEPT if ok else Decision.REJECT), ""


def _editorial_round(project: Project, llm, accept_defaults: bool, workers: int) -> None:
    from .stages import editorial
    outcome = editorial.run(project, llm,
                            AcceptEditorialUI() if accept_defaults else RichEditorialUI())
    if outcome.session_path:
        console.print(f"Editorial notes: [bold]{project.rel(outcome.session_path)}[/bold] "
                      f"({outcome.accepted}/{outcome.total} accepted)")
    if outcome.accepted:
        console.print("[bold]Applying accepted notes…[/bold]")
        _run(Context(project, llm, frozenset(), workers), GENERATION_STAGES)


def _run_looks(project: Project, llm, workers: int, only: frozenset[str] | None = None,
               stages=None) -> None:
    """Build every look the comic uses (scenes may override the comic's art style)."""
    from .store import Store
    for look in Store(project).looks():
        console.print(f"[dim]look: {look}[/dim]")
        ctx = Context(project, llm, frozenset(), workers, look=look, only=only)
        try:
            run_stages(ctx, stages or LOOK_STAGES, RichReporter())
        except StageFailed as e:
            if e.stage != "panel-art":
                console.print(f"[red]{escape(str(e))}[/red]")
                raise typer.Exit(1) from e
            # A panel that failed to draw doesn't block the comic: it renders as a
            # thumbnail, and the next render retries it.
            console.print(f"[yellow]{len(e.failures)} panel(s) not drawn (shown as "
                          f"thumbnails; re-run render to retry):[/yellow] "
                          + ", ".join(job.key.split(':', 1)[1] for job, _ in e.failures))


def _escape_all(value):
    """Escape Rich markup in every string of a dumped model (LLM output may contain brackets)."""
    if isinstance(value, dict):
        return {k: _escape_all(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_escape_all(v) for v in value]
    return escape(value) if isinstance(value, str) else value


class RichClarifyUI:
    SEVERITY_STYLE = {"blocker": "bold red", "major": "yellow", "minor": "dim"}

    def status(self, message: str) -> None:
        console.print(f"[dim]… {message}[/dim]")

    def show_evaluation(self, e: Evaluation, round_no: int) -> None:
        e = Evaluation.model_validate(_escape_all(e.model_dump()))
        body = [
            e.summary,
            "",
            f"[b]Intent:[/b] {e.intent} — {e.intent_rationale}",
            f"[b]Subject product:[/b] {e.subject_product}",
            f"[b]Key message:[/b] {e.key_message}",
            f"[b]Characters:[/b] {'; '.join(e.characters)}",
            f"[b]Direction:[/b] {e.direction}",
            f"[b]Beats ({len(e.beats)}, ~{e.estimated_panels} panels):[/b]",
            *[f"  {i}. {b}" for i, b in enumerate(e.beats, 1)],
        ]
        if e.concerns:
            body += ["", "[b]Concerns:[/b]"]
            for c in e.concerns:
                style = self.SEVERITY_STYLE.get(str(c.severity), "")
                body.append(f"  [{style}]{c.severity}[/{style}] ({c.area}) {c.description}")
        color = {"ready": "green", "needs-clarification": "yellow"}.get(str(e.readiness), "red")
        title = f"Evaluation · round {round_no} · [{color}]{e.readiness}[/{color}]"
        console.print(Panel("\n".join(body), title=title, expand=False))

    def ask(self, q: ClarifyingQuestion, index: int, total: int) -> str | None:
        raw_options = q.options
        q = ClarifyingQuestion.model_validate(_escape_all(q.model_dump()))
        console.print()
        console.print(f"[bold cyan]Question {index}/{total}:[/bold cyan] [bold]{q.question}[/bold]")
        console.print(f"[dim]Why: {q.why}[/dim]")
        for i, opt in enumerate(q.options, 1):
            console.print(f"  [cyan]{i}[/cyan]. {opt}")
        console.print(f"[dim]Enter to accept the default: {q.assumption}[/dim]")
        console.print("[dim]Type a number, your own answer, or /done to stop asking.[/dim]")
        reply = Prompt.ask("[cyan]›[/cyan]", default="", show_default=False).strip()
        if reply == "/done":
            raise clarify.EndSession
        if reply.isdigit() and 1 <= int(reply) <= len(q.options):
            return raw_options[int(reply) - 1]
        return reply or None


@app.command()
def author(
    path: ProjectArg = Path("."),
    model: ModelOpt = None,
    reclarify: Annotated[
        bool, typer.Option(help="Run clarification even if nothing changed.")
    ] = False,
    max_questions: Annotated[int, typer.Option(help="Max questions per round.")] = 5,
    no_cache: Annotated[bool, typer.Option(help="Bypass the LLM response cache.")] = False,
    accept_defaults: Annotated[bool, typer.Option(
        help="Don't ask: accept every question's stated assumption.")] = False,
    force: ForceOpt = None,
    workers: Annotated[int, typer.Option(help="Concurrent LLM calls per stage.")] = 4,
    edit: Annotated[bool, typer.Option(
        help="Run a script-editor round after generating the storyboard.")] = True,
) -> None:
    """Evaluate and clarify a comic prompt, then generate the structured storyboard."""
    project = _project(path)
    _locked(project)
    llm = _llm(project, model, no_cache)

    manifest = Manifest.load(project)
    changes = manifest.changed_sources(project)
    sessions = load_clarify_sessions(project)
    outdated = bool(sessions) and sessions[-1].protocol != clarify_protocol()

    if sessions and not changes and not outdated and not reclarify:
        console.print("[green]Prompt unchanged since last clarification — skipping.[/green]")
    else:
        if sessions and changes:
            listing = ", ".join(f"{p} ({c})" for p, c in changes.items())
            console.print(f"[yellow]Author input changed since last clarification:[/yellow] {escape(listing)}")
        elif outdated:
            console.print("[yellow]Clarification has new questions to resolve since your last "
                          "session (e.g. direction); asking only what's open.[/yellow]")
        ui = AcceptDefaultsUI() if accept_defaults else RichClarifyUI()
        outcome = clarify.run(project, llm, ui, max_questions=max_questions)
        console.print()
        console.print(f"Session notes: [bold]{project.rel(outcome.session_path)}[/bold]")
        if outcome.evaluation.readiness == Readiness.INSUFFICIENT:
            console.print(
                "[red]The prompt needs rework before a comic can be generated. "
                "See the concerns above, edit prompt.md, and run again.[/red]"
            )
            raise typer.Exit(1)

    console.print()
    _run(Context(project, llm, _force(force), workers), GENERATION_STAGES)
    if edit:
        _editorial_round(project, llm, accept_defaults, workers)
    console.print(f"[green]complete![/green] review the artifacts in "
                  f"[bold]{project.structured_dir}[/bold] — then "
                  f"[bold]comicify render --thumbnails[/bold]")


@app.command("edit")
def edit_cmd(
    path: ProjectArg = Path("."),
    model: ModelOpt = None,
    accept_defaults: Annotated[bool, typer.Option(
        help="Don't ask: accept high and medium priority notes.")] = False,
    workers: Annotated[int, typer.Option(help="Concurrent LLM calls per stage.")] = 4,
) -> None:
    """Run another script-editor round: review, decide, and apply accepted notes."""
    project = _project(path)
    _locked(project)
    _editorial_round(project, _llm(project, model, False), accept_defaults, workers)


@app.command()
def assets(
    path: ProjectArg = Path("."),
    model: ModelOpt = None,
    force: ForceOpt = None,
    no_cache: Annotated[bool, typer.Option(help="Bypass the LLM response cache.")] = False,
    workers: Annotated[int, typer.Option(help="Concurrent LLM calls per stage.")] = 4,
) -> None:
    """Build the art for the chosen look: style, fonts, characters, backdrops, props."""
    project = _project(path)
    _locked(project)
    _show_direction(project)
    _run_looks(project, _llm(project, model, no_cache), workers)


@app.command()
def render(
    path: ProjectArg = Path("."),
    backend: Annotated[list[str] | None, typer.Option(
        "--backend", "-b", help=f"Output format(s): {', '.join(BACKENDS)}.")] = None,
    fonts: Annotated[FontMode, typer.Option(help="How lettering is stored in the output.")]
        = FontMode.OUTLINE,
    local_fonts_ok: Annotated[bool, typer.Option(
        help="Acknowledge that --fonts system output only renders correctly on machines with "
             "the fonts installed.")] = False,
    skip_assets: Annotated[bool, typer.Option(
        help="Don't generate missing assets; draw placeholders instead.")] = False,
    colophon: Annotated[bool, typer.Option(
        help="Append a 'behind the panels' page with provenance and token usage.")] = True,
    appendix: Annotated[bool, typer.Option(
        help="Append pages showing every structured intermediate.")] = False,
    thumbnails: Annotated[bool, typer.Option(
        "--thumbnails", help="Storyboard fidelity: silhouettes and real lettering, no art "
                             "generation (free). Iterate on layout here.")] = False,
    model: ModelOpt = None,
    workers: Annotated[int, typer.Option(help="Concurrent LLM calls per stage.")] = 4,
) -> None:
    """Render the comic from structured/ and assets/ into rendered/vN/."""
    project = _project(path)
    _locked(project)
    if fonts == FontMode.SYSTEM and not local_fonts_ok:
        console.print("[red]--fonts system needs --local-fonts-ok: the output will only "
                      "render correctly where the bundled fonts are installed.[/red]")
        raise typer.Exit(2)
    _show_direction(project)
    from .render.compose import Fidelity
    from .store import Store
    if thumbnails:
        skip_assets = True
    ctx = Context(project, None if skip_assets else _llm(project, model, False), frozenset(),
                  workers)
    if skip_assets:
        _run_looks(project, None, workers, stages=LOOK_STAGES[:1])  # vendor art packs only
    else:
        _run_looks(project, ctx.llm, workers)
    backends = _force(backend) or {"svg", "png"}
    look = Store(project).direction().art.id
    result = render_comic(project, look, sorted(backends), fonts, colophon=colophon,
                          appendix=appendix,
                          fidelity=Fidelity.THUMBNAILS if thumbnails else Fidelity.FINAL)
    _report_missing(result.missing_assets)
    console.print(f"[green]complete![/green] find your comic in [bold]{result.out_dir}[/bold]")


@app.command()
def status(path: ProjectArg = Path(".")) -> None:
    """Show author-input changes and the state of every intermediate."""
    project = _project(path)
    manifest = Manifest.load(project)

    changes = manifest.changed_sources(project)
    sessions = load_clarify_sessions(project)
    if not sessions:
        console.print("No clarification yet. Run [bold]comicify author[/bold].")
    elif changes:
        console.print("[yellow]Author input changed since last clarification:[/yellow]")
        for p, c in changes.items():
            console.print(f"  {c:>8}  {p}")
    else:
        console.print("[green]Author input unchanged since last clarification.[/green]")

    files = {project.rel(f): f for f in project.structured_files()}
    for rel in manifest.entries:
        files.setdefault(rel, project.root / rel)
    if not files:
        console.print("No intermediates yet.")
        return
    style = {
        Status.FRESH: "green", Status.STALE: "yellow", Status.PINNED: "magenta",
        Status.MISSING: "red", Status.UNTRACKED: "dim",
    }
    table = Table("artifact", "status", "produced by")
    for rel, f in sorted(files.items()):
        st = manifest.status(project, f)
        entry = manifest.entries.get(rel)
        table.add_row(rel, f"[{style[st]}]{st}[/{style[st]}]", entry.produced_by if entry else "")
    console.print(table)


def _report_missing(missing: list[str]) -> None:
    if not missing:
        return
    shown = missing[:4]
    for m in shown:
        console.print(f"[yellow]not drawn yet (thumbnail shown):[/yellow] {escape(m)}")
    if len(missing) > len(shown):
        console.print(f"[yellow]…and {len(missing) - len(shown)} more[/yellow]")


@app.command()
def proof(
    path: ProjectArg = Path("."),
    count: Annotated[int, typer.Option(help="How many representative panels to draw.")] = 3,
    panel: Annotated[list[str] | None, typer.Option(
        "--panel", "-p", help="Draw these panel ids instead of an automatic sample.")] = None,
    backend: Annotated[list[str] | None, typer.Option(
        "--backend", "-b", help=f"Output format(s): {', '.join(BACKENDS)}.")] = None,
    model: ModelOpt = None,
    workers: Annotated[int, typer.Option(help="Concurrent LLM calls per stage.")] = 4,
) -> None:
    """Spot-check the look: draw a few representative panels at full fidelity and render the
    comic with the rest as thumbnails — before paying for every panel."""
    from .pipeline.look import PANEL_ART, ForMethod, proof_panels
    from .render.compose import Fidelity
    from .store import Store
    project = _project(path)
    _locked(project)
    _show_direction(project)
    llm = _llm(project, model, False)
    base = Context(project, llm, frozenset(), workers)
    chosen = _force(panel) and sorted(_force(panel)) or proof_panels(base, count)
    console.print(f"[bold]proofing:[/bold] {', '.join(chosen)}")
    # Foundations for every look, then finished art for the sampled panels only.
    _run_looks(project, llm, workers, only=frozenset(chosen),
               stages=[*LOOK_STAGES[:4], ForMethod(PANEL_ART, "per-panel")])
    look = Store(project).direction().art.id
    result = render_comic(project, look, sorted(_force(backend) or {"png", "pdf"}),
                          FontMode.OUTLINE, colophon=True, fidelity=Fidelity.FINAL)
    console.print(f"[green]proof ready:[/green] [bold]{result.out_dir}[/bold] "
                  f"({len(chosen)} finished panels; the rest are thumbnails)")


@app.command()
def styles(
    path: Annotated[Path | None, typer.Argument(
        help="Comic project (to include its own packs and show its selection).")] = None,
) -> None:
    """List the narrative, cinematography, and art packs you can mix and match."""
    project = _project(path) if path else (
        Project(Path(".").resolve()) if Path("prompt.md").is_file() else None)
    chosen = {}
    if project and project.artifact_path("direction").exists():
        from .store import Store
        d = Store(project).direction()
        chosen = {a: d.choice(a).id for a in Axis}
    from .direction import load_pack
    for axis, packs in available(project).items():
        table = Table(title=f"{axis}", title_justify="left", show_lines=False)
        table.add_column("id", style="bold")
        table.add_column("name")
        table.add_column("summary", overflow="fold")
        for pid, src in sorted(packs.items()):
            pack = load_pack(src)
            mark = " [green]●[/green]" if chosen.get(axis) == pid else ""
            origin = "" if src.builtin else " [cyan](project)[/cyan]"
            table.add_row(pid + mark, pack.name + origin, pack.summary)
        console.print(table)
    console.print("[dim]● = this comic's choice. Direction is decided during clarification and "
                  "recorded in structured/direction.yaml; edit it (or add a revision) to change "
                  "it.[/dim]")


@app.command()
def init(path: Annotated[Path, typer.Argument(help="New comic project directory.")]) -> None:
    """Create a new comic project with a prompt.md skeleton and config."""
    path.mkdir(parents=True, exist_ok=True)
    prompt = path / "prompt.md"
    if not prompt.exists():
        prompt.write_text(
            "# Title\n\nWhat is the subject product, and what moment should the comic show?\n\n"
            "# Characters\n\n# Story\n\n# Structure\n\n# Scene & vibe\n",
            encoding="utf-8",
        )
    cfg = path / CONFIG_FILENAME
    if not cfg.exists():
        write_config_template(cfg)
    Project.locate(path).ensure_layout()
    console.print(f"Created [bold]{path}[/bold]. Write your prompt in {prompt}.")
