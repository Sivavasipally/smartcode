"""Sandboxed subprocess execution (Harness pattern: Sandboxed Execution).

All external tools (linters, compilers, test commands) run through this one
choke point: explicit cwd jail, wall-clock timeout, captured output, no shell
string interpolation for tool argv (only the user-supplied test command goes
through the shell, and that is the user's own declared command).
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RunOutcome:
    ok: bool
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    error: str = ""

    @property
    def detail(self) -> str:
        if self.error:
            return self.error
        if self.timed_out:
            return "timed out"
        out = (self.stdout + "\n" + self.stderr).strip()
        return out[:2000]


def run_sandboxed(
    argv: list[str] | str,
    *,
    cwd: str | Path,
    timeout_s: int = 60,
    shell: bool = False,
) -> RunOutcome:
    """Run a tool inside ``cwd`` with a hard timeout; never raises."""
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd),
            shell=shell,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
        )
        return RunOutcome(
            ok=proc.returncode == 0,
            exit_code=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
        )
    except subprocess.TimeoutExpired:
        return RunOutcome(ok=False, exit_code=None, stdout="", stderr="",
                          timed_out=True)
    except FileNotFoundError as e:
        return RunOutcome(ok=False, exit_code=None, stdout="", stderr="",
                          error=f"tool not found: {e}")
    except OSError as e:
        return RunOutcome(ok=False, exit_code=None, stdout="", stderr="", error=str(e))
