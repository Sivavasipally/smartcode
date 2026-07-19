"""Rich CLI: ``smartcode gen | modify | review | providers | doctor``."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from .agent import CodeAgent
from .config import load_settings
from .models import EvidencePackage, TaskContract

app = typer.Typer(
    name="smartcode",
    help="Local-first, multi-provider code generation agent (LangGraph).",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()

_NODE_STYLE = {
    "classify_intent": "cyan", "retriever": "blue", "planner": "magenta",
    "coder": "green", "verifier": "yellow", "critic": "red",
    "repair": "bright_red", "hitl_gate": "bright_yellow", "finalize": "bright_green",
}


def _on_event(event: dict) -> None:
    node = event.get("node", "?")
    style = _NODE_STYLE.get(node, "white")
    console.print(f"  [dim]{event.get('elapsed_s', 0):>6.1f}s[/dim] "
                  f"[{style}]{node:<15}[/{style}] {event.get('message', '')}")


def _print_diff(diff: str, max_lines: int = 80) -> None:
    for line in diff.splitlines()[:max_lines]:
        if line.startswith("+") and not line.startswith("+++"):
            console.print(f"[green]{line}[/green]", highlight=False)
        elif line.startswith("-") and not line.startswith("---"):
            console.print(f"[red]{line}[/red]", highlight=False)
        elif line.startswith("@@"):
            console.print(f"[cyan]{line}[/cyan]", highlight=False)
        else:
            console.print(f"[dim]{line}[/dim]", highlight=False)
    if len(diff.splitlines()) > max_lines:
        console.print(f"[dim]… {len(diff.splitlines()) - max_lines} more diff lines[/dim]")


def _approval(task: TaskContract, edits: list[dict], files: dict) -> bool:
    from .editing import unified_diffs
    console.print()
    table = Table(title="Pending writes (HITL gate)", show_lines=False)
    table.add_column("action")
    table.add_column("path")
    table.add_column("summary")
    for e in edits:
        table.add_row(e.get("action", "?"), e.get("path", "?"),
                      (e.get("summary") or "")[:60])
    console.print(table)
    for path, diff in unified_diffs(files).items():
        if diff.strip():
            console.print(f"\n[bold]{path}[/bold]")
            _print_diff(diff, max_lines=40)
    return Confirm.ask(f"Apply these edits (risk tier: {task.risk_tier.value})?",
                       default=True)


def _proposal_review(task, proposal, round_no: int) -> dict:
    """Interactive change-set review for workspace runs."""
    console.print()
    table = Table(title=f"Proposed change-set (round {round_no})")
    table.add_column("#")
    table.add_column("action")
    table.add_column("file")
    table.add_column("reason")
    for i, t in enumerate(proposal.targets, 1):
        style = "green" if t.action == "create" else "yellow"
        table.add_row(str(i), f"[{style}]{t.action}[/{style}]", t.path, t.reason[:70])
    console.print(table)
    if proposal.rationale:
        console.print(f"[dim]rationale: {proposal.rationale}[/dim]")
    for q in proposal.open_questions:
        console.print(f"[yellow]open question:[/yellow] {q}")

    choice = typer.prompt(
        "\n[a]pprove all / numbers to approve subset (e.g. 1,3) / "
        "[s]uggest changes / [r]eject", default="a").strip().lower()
    if choice in ("a", "approve", "y", "yes"):
        return {"decision": "approve"}
    if choice in ("r", "reject", "n", "no"):
        return {"decision": "reject"}
    if choice in ("s", "suggest"):
        feedback = typer.prompt("guidance for the selector")
        return {"decision": "revise", "feedback": feedback}
    try:
        picks = {int(x) for x in choice.replace(" ", "").split(",") if x}
        selected = [t.path for i, t in enumerate(proposal.targets, 1) if i in picks]
        if selected:
            return {"decision": "approve", "selected": selected}
    except ValueError:
        pass
    console.print("[red]unrecognised choice — treating as reject[/red]")
    return {"decision": "reject"}


def _make_agent(provider: Optional[str], yes: bool, verbose: bool,
                test_cmd: Optional[str]) -> CodeAgent:
    overrides: dict = {}
    if test_cmd:
        overrides["test_command"] = test_cmd
    settings = load_settings(provider=provider, verbose=verbose, **overrides)
    callback = (lambda *_: True) if yes else _approval
    proposal_cb = (lambda *_: {"decision": "approve"}) if yes else _proposal_review
    return CodeAgent(settings=settings, approval_callback=callback,
                     proposal_callback=proposal_cb,
                     on_event=_on_event if verbose else None)


def _show_result(ev: EvidencePackage) -> None:
    status_style = {"success": "bold green", "best_effort": "yellow",
                    "rejected": "bold red", "review_only": "cyan"}[ev.status]
    lines = [f"[{status_style}]status: {ev.status}[/{status_style}]  "
             f"(revisions: {ev.revisions})"]

    if ev.plan and ev.plan.steps:
        lines.append("\n[bold]Plan[/bold]: " + ev.plan.approach)
        for i, s in enumerate(ev.plan.steps, 1):
            lines.append(f"  {i}. {s.description}")

    if ev.verify:
        mark = "[green]PASS[/green]" if ev.verify.overall_ok else "[red]FAIL[/red]"
        lines.append(f"\n[bold]Verify[/bold] {mark} {ev.verify.summary}")
        if ev.verify.lint_ok is not None:
            lines.append(f"  lint: {'ok' if ev.verify.lint_ok else 'FAILED'}")
        if ev.verify.tests_ok is not None:
            lines.append(f"  tests: {'ok' if ev.verify.tests_ok else 'FAILED'}")

    if ev.critique:
        lines.append(f"\n[bold]Critique[/bold] score={ev.critique.score:.2f}  "
                     f"acceptance={'met' if ev.critique.satisfies_acceptance else 'NOT met'}")
        for f in ev.critique.findings:
            loc = f" ({f.location})" if f.location else ""
            lines.append(f"  [{'red' if f.severity in ('blocker', 'major') else 'yellow'}]"
                         f"{f.severity}[/]: {f.message}{loc}")
            if f.suggestion:
                lines.append(f"      -> {f.suggestion}")

    if ev.applied:
        lines.append("\n[bold]Written[/bold]:")
        for a in ev.applied:
            if a.applied:
                lines.append(f"  [green]written[/green] {a.path} ({a.bytes_written} bytes)")
            else:
                lines.append(f"  [red]blocked[/red] {a.path}: {a.error}")

    if "error:" in (ev.task.notes or ""):
        lines.append(f"\n[red]{ev.task.notes.strip()}[/red]")

    console.print(Panel("\n".join(lines), title="smartcode result", expand=False))

    for path, diff in (ev.diffs or {}).items():
        if diff.strip():
            console.print(f"[bold]diff: {path}[/bold]")
            _print_diff(diff)


# ---------------------------------------------------------------------------
_PROVIDER_OPT = typer.Option(None, "--provider", "-p",
                             help="local | groq | anthropic | openai | google | mock")
_YES_OPT = typer.Option(False, "--yes", "-y", help="auto-approve writes (skip HITL prompt)")
_VERBOSE_OPT = typer.Option(False, "--verbose", "-v", help="live per-node trace")
_RISK_OPT = typer.Option(None, "--risk", help="low | medium | high write-gate tier")
_TEST_OPT = typer.Option(None, "--test-cmd", help="test command to run during verification")


@app.command()
def gen(
    objective: str = typer.Argument(..., help="what to build"),
    lang: Optional[str] = typer.Option(None, "--lang", "-l"),
    framework: Optional[str] = typer.Option(None, "--framework", "-f"),
    out: Optional[str] = typer.Option(
        None, "--out", "-o",
        help="output file path; omit to let the agent PROPOSE the location "
             "from the code under --root (shown for approval first)"),
    root: Optional[str] = typer.Option(
        None, "--root", "-r",
        help="codebase to place the new code in (used when --out is omitted; "
             "defaults to the current directory)"),
    acceptance: List[str] = typer.Option([], "--accept", "-a",
                                         help="acceptance criterion (repeatable)"),
    provider: Optional[str] = _PROVIDER_OPT,
    risk: Optional[str] = _RISK_OPT,
    yes: bool = _YES_OPT,
    verbose: bool = _VERBOSE_OPT,
    test_cmd: Optional[str] = _TEST_OPT,
):
    """Generate NEW code. Without --out, the agent proposes folder + file
    name(s) from the existing codebase and waits for your approval."""
    agent = _make_agent(provider, yes, verbose, test_cmd)
    console.print(f"[bold]smartcode gen[/bold] ({agent.settings.provider}): {objective}")
    ev = agent.generate(objective, language=lang, framework=framework,
                        out_path=out, root=None if out else (root or "."),
                        acceptance=acceptance or None, risk=risk)
    _show_result(ev)
    raise typer.Exit(0 if ev.status in ("success", "best_effort") else 1)


@app.command()
def modify(
    paths: List[str] = typer.Argument(..., help="existing file(s) to change"),
    instruction: str = typer.Argument(..., help="what to change"),
    lang: Optional[str] = typer.Option(None, "--lang", "-l"),
    framework: Optional[str] = typer.Option(None, "--framework", "-f"),
    acceptance: List[str] = typer.Option([], "--accept", "-a"),
    provider: Optional[str] = _PROVIDER_OPT,
    risk: Optional[str] = _RISK_OPT,
    yes: bool = _YES_OPT,
    verbose: bool = _VERBOSE_OPT,
    test_cmd: Optional[str] = _TEST_OPT,
):
    """MODIFY/UPDATE existing code."""
    for p in paths:
        if not Path(p).exists():
            console.print(f"[red]file not found:[/red] {p}")
            raise typer.Exit(2)
    agent = _make_agent(provider, yes, verbose, test_cmd)
    console.print(f"[bold]smartcode modify[/bold] ({agent.settings.provider}): {instruction}")
    ev = agent.modify(paths, instruction, language=lang, framework=framework,
                      acceptance=acceptance or None, risk=risk)
    _show_result(ev)
    raise typer.Exit(0 if ev.status in ("success", "best_effort") else 1)


@app.command()
def ws(
    objective: str = typer.Argument(..., help="what to change across the workspace"),
    root: str = typer.Option(".", "--root", "-r",
                             help="workspace folder (may contain multiple repos)"),
    lang: Optional[str] = typer.Option(None, "--lang", "-l"),
    framework: Optional[str] = typer.Option(None, "--framework", "-f"),
    acceptance: List[str] = typer.Option([], "--accept", "-a"),
    provider: Optional[str] = _PROVIDER_OPT,
    risk: Optional[str] = _RISK_OPT,
    yes: bool = _YES_OPT,
    verbose: bool = _VERBOSE_OPT,
    test_cmd: Optional[str] = _TEST_OPT,
):
    """Folder-scale run: scan all repos under --root, review the proposed
    change-set (approve / narrow / suggest), then generate + apply."""
    if not Path(root).is_dir():
        console.print(f"[red]not a directory:[/red] {root}")
        raise typer.Exit(2)
    agent = _make_agent(provider, yes, verbose, test_cmd)
    console.print(f"[bold]smartcode ws[/bold] ({agent.settings.provider}): "
                  f"{objective}  [dim]root={root}[/dim]")
    ev = agent.workspace(objective, root=root, language=lang, framework=framework,
                         acceptance=acceptance or None, risk=risk)
    _show_result(ev)
    raise typer.Exit(0 if ev.status in ("success", "best_effort") else 1)


@app.command()
def review(
    paths: List[str] = typer.Argument(..., help="file(s) to review"),
    focus: Optional[str] = typer.Option(None, "--focus",
                                        help="what to focus the review on"),
    provider: Optional[str] = _PROVIDER_OPT,
    verbose: bool = _VERBOSE_OPT,
):
    """REVIEW code — findings only, no writes."""
    for p in paths:
        if not Path(p).exists():
            console.print(f"[red]file not found:[/red] {p}")
            raise typer.Exit(2)
    agent = _make_agent(provider, True, verbose, None)
    console.print(f"[bold]smartcode review[/bold] ({agent.settings.provider}): "
                  f"{', '.join(paths)}")
    ev = agent.review(paths, focus=focus)
    _show_result(ev)
    raise typer.Exit(0)


@app.command()
def providers():
    """Show provider availability."""
    from .providers.registry import available_providers
    settings = load_settings()
    table = Table(title="Providers")
    table.add_column("id")
    table.add_column("status")
    table.add_column("detail")
    table.add_column("model")
    from .config import DEFAULT_MODELS
    for pid, (ok, reason) in available_providers(settings).items():
        model = settings.model_name if pid == settings.provider else \
            getattr(settings, f"{pid}_model", DEFAULT_MODELS.get(pid, "-"))
        mark = "[green]available[/green]" if ok else "[red]unavailable[/red]"
        active = " [bold](active)[/bold]" if pid == settings.provider else ""
        table.add_row(pid + active, mark, reason, str(model))
    console.print(table)


@app.command()
def runs(limit: int = typer.Option(10, "--limit", "-n", help="how many to show")):
    """List recent runs from the evidence ledger (.smartcode/runs)."""
    import json as _json

    settings = load_settings()
    run_dir = settings.data_dir / "runs"
    files = sorted(run_dir.glob("evidence-*.json"), reverse=True)[:limit]
    if not files:
        console.print(f"[dim]no runs recorded under {run_dir}[/dim]")
        raise typer.Exit(0)

    table = Table(title=f"Recent runs ({run_dir})")
    table.add_column("when")
    table.add_column("status")
    table.add_column("intent")
    table.add_column("rev")
    table.add_column("objective")
    for f in files:
        try:
            data = _json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        status = data.get("status", "?")
        style = {"success": "green", "best_effort": "yellow",
                 "rejected": "red", "review_only": "cyan"}.get(status, "white")
        task = data.get("task", {})
        table.add_row(
            f.stem.replace("evidence-", ""),
            f"[{style}]{status}[/{style}]",
            task.get("intent", "?"),
            str(data.get("revisions", 0)),
            (task.get("objective") or "")[:70],
        )
    console.print(table)


@app.command()
def doctor():
    """Environment self-check: deps, grammars, providers, local model."""
    from .providers.registry import available_providers
    from .retrieval.tree_sitter import parse_source, supported_languages

    settings = load_settings()
    table = Table(title="smartcode doctor")
    table.add_column("check")
    table.add_column("result")

    table.add_row("python", sys.version.split()[0])
    table.add_row("provider (active)", settings.provider)

    langs = supported_languages()
    table.add_row("tree-sitter grammars", f"{len(langs)}: {', '.join(langs)}")
    smoke = parse_source("def f():\n    return 1\n", "python")
    table.add_row("tree-sitter smoke", "[green]ok[/green]" if smoke.ok and smoke.names == ["f"]
                  else f"[red]failed: {smoke.error}[/red]")

    for pid, (ok, reason) in available_providers(settings).items():
        table.add_row(f"provider: {pid}",
                      f"[green]{reason}[/green]" if ok else f"[yellow]{reason}[/yellow]")

    model_dir = Path(settings.local_model_path)
    table.add_row("local model dir",
                  f"[green]{model_dir}[/green]" if model_dir.exists()
                  else f"[yellow]missing: {model_dir}[/yellow]")
    try:
        import torch
        cuda = torch.cuda.is_available()
        dev = torch.cuda.get_device_name(0) if cuda else "cpu only"
        table.add_row("torch", f"{torch.__version__} ({dev})")
    except ImportError:
        table.add_row("torch", "[yellow]not installed (uv sync --extra local)[/yellow]")

    table.add_row("data dir", str(settings.data_dir.resolve()))
    console.print(table)


if __name__ == "__main__":
    app()
