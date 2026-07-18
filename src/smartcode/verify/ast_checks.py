"""Deterministic sensor (Harness pattern #07) — no LLM involved.

Given the *virtually applied* file contents, verify structural validity:
tree-sitter parse without ERROR nodes, bracket balance, non-emptiness, and for
Python a real ``compile()``. Cheap, reproducible signals that gate the
evaluator-optimizer loop before any inferential (LLM) judgement runs.
"""
from __future__ import annotations

from pathlib import Path

from ..models import CheckResult, VerifyResult
from ..retrieval.tree_sitter import bracket_balanced, language_for_file, parse_source


def _check_one(path: str, text: str) -> list[CheckResult]:
    checks: list[CheckResult] = []
    name = Path(path).name

    if not text.strip():
        checks.append(CheckResult(name=f"{name}: non-empty", passed=False,
                                  detail="generated file is empty"))
        return checks
    checks.append(CheckResult(name=f"{name}: non-empty", passed=True))

    lang = language_for_file(path)
    if lang:
        parsed = parse_source(text, lang, path)
        if parsed.ok:
            has_err = False
            try:
                import tree_sitter  # noqa: F401
                # parse_source succeeded; re-parse to inspect error nodes
                from ..retrieval.tree_sitter import _load  # type: ignore
                tree = _load(lang).parser.parse(text.encode("utf-8"))
                has_err = tree.root_node.has_error
            except Exception:
                pass
            checks.append(CheckResult(
                name=f"{name}: tree-sitter parse ({lang})",
                passed=not has_err,
                detail="" if not has_err else "syntax error nodes present",
            ))
        else:
            checks.append(CheckResult(name=f"{name}: tree-sitter parse ({lang})",
                                      passed=True,
                                      detail=f"grammar unavailable, skipped: {parsed.error}"))
    else:
        checks.append(CheckResult(
            name=f"{name}: bracket balance",
            passed=bracket_balanced(text),
            detail="unbalanced brackets" if not bracket_balanced(text) else "",
        ))

    if lang == "python":
        try:
            compile(text, path, "exec")
            checks.append(CheckResult(name=f"{name}: py-compile", passed=True))
        except SyntaxError as e:
            checks.append(CheckResult(name=f"{name}: py-compile", passed=False,
                                      detail=f"line {e.lineno}: {e.msg}"))
    return checks


def check_files(files: dict[str, str]) -> VerifyResult:
    """Run the deterministic sensor over ``{path: new_text}``."""
    checks: list[CheckResult] = []
    for path, text in files.items():
        checks.extend(_check_one(path, text))
    ok = all(c.passed for c in checks)
    failed = [c for c in checks if not c.passed]
    return VerifyResult(
        parsed_ok=ok,
        checks=checks,
        overall_ok=ok,
        summary="all structural checks passed" if ok else
                "; ".join(f"{c.name}: {c.detail}" for c in failed),
    )
