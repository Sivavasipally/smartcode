"""Best-effort external linters — used only when the tool is on PATH.

Each entry lints a *file* in a temp workspace. Absence of a linter is not a
failure (lint_ok stays None); a present linter that rejects the code is a hard
signal fed into the repair loop.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from ..retrieval.tree_sitter import language_for_file
from .runner import RunOutcome, run_sandboxed

#: language → (tool, argv builder). Only fast, parse-level checks — no project config needed.
# Tools are resolved to absolute paths: npm shims are .cmd files on Windows and
# bare names fail under subprocess without the resolved path.
def _cmd_for(lang: str, file: Path) -> list[str] | None:
    if lang == "python":
        ruff = shutil.which("ruff")
        if ruff:
            return [ruff, "check", "--no-cache", "--select", "E9,F63,F7,F82", str(file)]
    if lang == "javascript":
        node = shutil.which("node")
        if node:
            return [node, "--check", str(file)]
    if lang == "typescript":
        tsc = shutil.which("tsc")
        if tsc:
            return [tsc, "--noEmit", "--skipLibCheck", str(file)]
    if lang == "go":
        gofmt = shutil.which("gofmt")
        if gofmt:
            return [gofmt, "-l", str(file)]
    return None


def run_linters(files: dict[str, str], timeout_s: int = 60) -> tuple[bool | None, str]:
    """Lint the materialized files. Returns (ok|None, detail)."""
    results: list[tuple[str, RunOutcome]] = []
    with tempfile.TemporaryDirectory(prefix="smartcode-lint-") as tmp:
        tmpdir = Path(tmp)
        for path, text in files.items():
            lang = language_for_file(path)
            if not lang:
                continue
            target = tmpdir / Path(path).name
            target.write_text(text, encoding="utf-8")
            cmd = _cmd_for(lang, target)
            if not cmd:
                continue
            out = run_sandboxed(cmd, cwd=tmpdir, timeout_s=timeout_s)
            # gofmt -l prints the filename when formatting differs → treat as pass
            if cmd[0] == "gofmt":
                out.ok = out.exit_code == 0
            results.append((path, out))

    if not results:
        return None, "no applicable linters found on PATH"
    bad = [(p, o) for p, o in results if not o.ok]
    if not bad:
        return True, f"{len(results)} file(s) linted clean"
    detail = "; ".join(f"{p}: {o.detail[:400]}" for p, o in bad)
    return False, detail
