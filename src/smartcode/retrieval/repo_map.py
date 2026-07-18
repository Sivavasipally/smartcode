"""Progressive-disclosure repo map.

A cheap, compact index — paths + symbol signatures, never bodies — that gives
the planner/coder situational awareness of the codebase without paying the
token cost of file contents. Bodies are only loaded later, on demand, by the
retriever (Just-in-Time Context).
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from ..config import LANG_BY_EXT
from .tree_sitter import parse_file

_SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__",
    "dist", "build", "target", ".smartcode", ".idea", ".vscode", ".tox",
}
_MAX_FILES = 200
_MAX_SYMBOLS_PER_FILE = 25


def _iter_source_files(root: Path) -> Iterable[Path]:
    stack = [root]
    seen = 0
    while stack:
        d = stack.pop()
        try:
            entries = sorted(d.iterdir())
        except OSError:
            continue
        for p in entries:
            if p.is_dir():
                if p.name not in _SKIP_DIRS and not p.name.startswith("."):
                    stack.append(p)
            elif p.suffix.lower() in LANG_BY_EXT:
                yield p
                seen += 1
                if seen >= _MAX_FILES:
                    return


def build_repo_map(root: str | Path, focus: Iterable[str | Path] = ()) -> str:
    """Render a compact ``path → symbols`` map.

    ``focus`` files always get full symbol listings; other files are listed by
    path only, keeping the map inside a few hundred tokens for large repos.
    """
    root = Path(root)
    focus_set = {Path(f).resolve() for f in focus}
    lines: list[str] = [f"# Repo map: {root}"]

    if root.is_file():
        files: list[Path] = [root]
    else:
        files = list(_iter_source_files(root))

    for f in files:
        rel = f.name if root.is_file() else str(f.relative_to(root))
        if focus_set and f.resolve() not in focus_set:
            lines.append(f"- {rel}")
            continue
        result = parse_file(f)
        if not result.ok:
            lines.append(f"- {rel}  (unparsed: {result.error})")
            continue
        syms = ", ".join(
            f"{s.name}[{s.start_line}-{s.end_line}]"
            for s in result.symbols[:_MAX_SYMBOLS_PER_FILE]
        )
        suffix = " …" if len(result.symbols) > _MAX_SYMBOLS_PER_FILE else ""
        lines.append(f"- {rel} ({result.language}, {result.n_lines} lines): {syms}{suffix}")
    return "\n".join(lines)
