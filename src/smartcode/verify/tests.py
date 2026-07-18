"""Run the project's configured test command, if any.

Tests only run when the user explicitly declares a command
(``SMARTCODE_TEST_COMMAND`` / ``--test-cmd``): the agent never guesses a test
runner, because running arbitrary inferred commands is exactly what the
sandboxed-execution pattern exists to prevent.
"""
from __future__ import annotations

from pathlib import Path

from .runner import run_sandboxed


def run_tests(command: str | None, cwd: str | Path = ".",
              timeout_s: int = 300) -> tuple[bool | None, str]:
    """Returns (ok|None, detail). None = no test command configured."""
    command = (command or "").strip()
    # A leading '#' means an un-stripped .env comment leaked in, not a command.
    if not command or command.startswith("#"):
        return None, "no test command configured"
    out = run_sandboxed(command, cwd=cwd, timeout_s=timeout_s, shell=True)
    return out.ok, out.detail
