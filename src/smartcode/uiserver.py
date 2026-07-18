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


_approvals: dict[str, _Approval] = {}
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
        gate = _Approval()
        _approvals[run_id] = gate
        send({"type": "approval_request", "runId": run_id,
              "risk": task.risk_tier.value, "edits": edits})
        gate.ready.wait(timeout=_APPROVAL_TIMEOUT_S)
        _approvals.pop(run_id, None)
        return gate.approved

    overrides = {
        k: params[k]
        for k in ("test_command", "max_revisions", "run_linters", "run_tests",
                  "context_token_budget")
        if params.get(k) not in (None, "")
    }
    try:
        agent = CodeAgent(provider=params.get("provider") or None,
                          approval_callback=approval_cb,
                          on_event=on_event, **overrides)
        send({"type": "run_started", "runId": run_id,
              "provider": agent.settings.provider})

        mode = params.get("mode", "generate")
        objective = (params.get("objective") or "").strip()
        acceptance = [a for a in (params.get("acceptance") or []) if a.strip()]
        common = dict(acceptance=acceptance or None, session_id=run_id)

        if mode == "generate":
            evidence = agent.generate(
                objective,
                language=params.get("language") or None,
                framework=params.get("framework") or None,
                out_path=params.get("out_path") or None,
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


def _handle_approval_response(msg: dict) -> None:
    gate = _approvals.get(str(msg.get("id")))
    if gate:
        gate.approved = bool(msg.get("approved"))
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
        elif cmd == "shutdown":
            break
        else:
            send({"type": "error", "message": f"unknown cmd {cmd!r}"})
    # Drain in-flight runs so results aren't lost on graceful shutdown / stdin EOF.
    for t in workers:
        t.join(timeout=120)


if __name__ == "__main__":
    main()
