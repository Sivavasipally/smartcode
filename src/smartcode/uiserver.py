"""stdio JSON bridge for the Electron UI.

The Electron main process spawns ``python -m smartcode.uiserver`` and speaks
line-delimited JSON over stdin/stdout — no network, no extra dependencies.

Inbound commands (one JSON object per line):
    {"id": "...", "cmd": "init"}
    {"id": "...", "cmd": "run", "params": {mode, objective, provider, language,
        framework, out_path, paths, acceptance, risk, test_command,
        max_revisions, run_linters, run_tests}}
    {"id": "<runId>", "cmd": "approval_response", "approved": true|false}

Outbound messages:
    {"type": "init", ...}                     capabilities + provider health
    {"type": "run_started", "runId": ...}
    {"type": "event", "runId", "event": {ts, node, message, ...}}
    {"type": "approval_request", "runId", "edits": [...], "risk": "..."}
    {"type": "result", "runId", "evidence": {...}, "written_files": {path: text}}
    {"type": "error", "runId", "message": "..."}

stdout carries ONLY these JSON lines; all diagnostics go to stderr.
"""
from __future__ import annotations

import json
import sys
import threading
import traceback
from pathlib import Path

from .agent import CodeAgent
from .config import DEFAULT_MODELS, LANG_BY_EXT, load_settings
from .models import TaskContract
from .skills.registry import FRAMEWORK_LANGUAGE

_out_lock = threading.Lock()


def send(obj: dict) -> None:
    with _out_lock:
        sys.stdout.write(json.dumps(obj, default=str) + "\n")
        sys.stdout.flush()


class _Approval:
    def __init__(self) -> None:
        self.ready = threading.Event()
        self.approved = False


class _ProposalGate:
    def __init__(self) -> None:
        self.ready = threading.Event()
        self.result: dict = {"decision": "reject"}


_approvals: dict[str, _Approval] = {}
_proposal_gates: dict[str, _ProposalGate] = {}
_APPROVAL_TIMEOUT_S = 900


def _handle_init(msg: dict) -> None:
    from .providers.registry import available_providers
    from .retrieval.tree_sitter import supported_languages

    settings = load_settings()
    providers = {
        pid: {"ok": ok, "reason": reason,
              "model": DEFAULT_MODELS.get(pid) if pid in ("local", "mock")
              else getattr(settings, f"{pid}_model", "")}
        for pid, (ok, reason) in available_providers(settings).items()
    }
    send({
        "type": "init",
        "id": msg.get("id"),
        "providers": providers,
        "languages": sorted(set(LANG_BY_EXT.values())),
        "frameworks": sorted(FRAMEWORK_LANGUAGE),
        "grammars": supported_languages(),
        "defaults": {
            "provider": settings.provider,
            "risk": settings.default_risk_tier,
            "max_revisions": settings.max_revisions,
            "cwd": str(Path.cwd()),
        },
    })


def _handle_run(msg: dict) -> None:
    run_id = str(msg.get("id") or "run")
    params = msg.get("params") or {}

    def on_event(event: dict) -> None:
        send({"type": "event", "runId": run_id, "event": event})

    def approval_cb(task: TaskContract, edits: list[dict], files: dict) -> bool:
        from .editing import unified_diffs
        gate = _Approval()
        _approvals[run_id] = gate
        send({"type": "approval_request", "runId": run_id,
              "risk": task.risk_tier.value, "edits": edits,
              "diffs": unified_diffs(files)})
        gate.ready.wait(timeout=_APPROVAL_TIMEOUT_S)
        _approvals.pop(run_id, None)
        return gate.approved

    def proposal_cb(task: TaskContract, proposal, round_no: int) -> dict:
        gate = _ProposalGate()
        _proposal_gates[run_id] = gate
        send({"type": "proposal_request", "runId": run_id, "round": round_no,
              "proposal": proposal.model_dump()})
        gate.ready.wait(timeout=_APPROVAL_TIMEOUT_S)
        _proposal_gates.pop(run_id, None)
        return gate.result

    overrides = {
        k: params[k]
        for k in ("test_command", "max_revisions", "run_linters", "run_tests",
                  "context_token_budget")
        if params.get(k) not in (None, "")
    }
    try:
        agent = CodeAgent(provider=params.get("provider") or None,
                          approval_callback=approval_cb,
                          proposal_callback=proposal_cb,
                          on_event=on_event, **overrides)
        send({"type": "run_started", "runId": run_id,
              "provider": agent.settings.provider})

        mode = params.get("mode", "generate")
        objective = (params.get("objective") or "").strip()
        acceptance = [a for a in (params.get("acceptance") or []) if a.strip()]
        common = dict(acceptance=acceptance or None, session_id=run_id)

        if mode == "generate":
            out_path = params.get("out_path") or None
            evidence = agent.generate(
                objective,
                language=params.get("language") or None,
                framework=params.get("framework") or None,
                out_path=out_path,
                root=None if out_path else (params.get("workspace_root") or None),
                risk=params.get("risk") or None, **common,
            )
        elif mode == "modify":
            evidence = agent.modify(
                params.get("paths") or [], objective,
                language=params.get("language") or None,
                framework=params.get("framework") or None,
                risk=params.get("risk") or None, **common,
            )
        elif mode == "review":
            evidence = agent.review(params.get("paths") or [],
                                    focus=objective or None, session_id=run_id)
        elif mode == "workspace":
            evidence = agent.workspace(
                objective, root=params.get("workspace_root") or ".",
                language=params.get("language") or None,
                framework=params.get("framework") or None,
                risk=params.get("risk") or None, **common,
            )
        else:
            raise ValueError(f"unknown mode {mode!r}")

        written: dict[str, str] = {}
        for applied in evidence.applied:
            if applied.applied:
                try:
                    written[applied.path] = Path(applied.path).read_text(
                        encoding="utf-8", errors="replace")
                except OSError:
                    pass
        send({"type": "result", "runId": run_id,
              "evidence": evidence.model_dump(mode="json"),
              "written_files": written})
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        send({"type": "error", "runId": run_id, "message": str(e)})


def _handle_history(msg: dict) -> None:
    """Summaries of recent evidence packages for the History tab."""
    settings = load_settings()
    run_dir = settings.data_dir / "runs"
    items = []
    for f in sorted(run_dir.glob("evidence-*.json"), reverse=True)[:25]:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        items.append({
            "file": f.name,
            "when": f.stem.replace("evidence-", ""),
            "status": data.get("status"),
            "intent": (data.get("task") or {}).get("intent"),
            "objective": ((data.get("task") or {}).get("objective") or "")[:120],
            "revisions": data.get("revisions", 0),
        })
    send({"type": "history", "id": msg.get("id"), "runs": items})


def _handle_load_run(msg: dict) -> None:
    """Full evidence package for one past run (History tab drill-down)."""
    settings = load_settings()
    name = Path(str(msg.get("file", ""))).name   # no traversal
    path = settings.data_dir / "runs" / name
    if not (name.startswith("evidence-") and path.is_file()):
        send({"type": "error", "id": msg.get("id"), "message": f"unknown run {name!r}"})
        return
    try:
        send({"type": "run_loaded", "id": msg.get("id"),
              "evidence": json.loads(path.read_text(encoding="utf-8"))})
    except (OSError, ValueError) as e:
        send({"type": "error", "id": msg.get("id"), "message": str(e)})


def _handle_approval_response(msg: dict) -> None:
    gate = _approvals.get(str(msg.get("id")))
    if gate:
        gate.approved = bool(msg.get("approved"))
        gate.ready.set()


def _handle_proposal_response(msg: dict) -> None:
    gate = _proposal_gates.get(str(msg.get("id")))
    if gate:
        gate.result = {
            "decision": msg.get("decision", "reject"),
            "feedback": msg.get("feedback", ""),
            "selected": msg.get("selected"),
        }
        gate.ready.set()


def main() -> None:
    send({"type": "ready"})
    workers: list[threading.Thread] = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            send({"type": "error", "message": f"bad json: {line[:200]}"})
            continue
        cmd = msg.get("cmd")
        if cmd == "init":
            t = threading.Thread(target=_handle_init, args=(msg,), daemon=True)
            t.start()
            workers.append(t)
        elif cmd == "run":
            t = threading.Thread(target=_handle_run, args=(msg,), daemon=True)
            t.start()
            workers.append(t)
        elif cmd == "approval_response":
            _handle_approval_response(msg)
        elif cmd == "proposal_response":
            _handle_proposal_response(msg)
        elif cmd == "history":
            threading.Thread(target=_handle_history, args=(msg,), daemon=True).start()
        elif cmd == "load_run":
            threading.Thread(target=_handle_load_run, args=(msg,), daemon=True).start()
        elif cmd == "shutdown":
            break
        else:
            send({"type": "error", "message": f"unknown cmd {cmd!r}"})
    # Drain in-flight runs so results aren't lost on graceful shutdown / stdin EOF.
    for t in workers:
        t.join(timeout=120)


if __name__ == "__main__":
    main()
