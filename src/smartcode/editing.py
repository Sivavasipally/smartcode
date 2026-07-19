"""Deterministic application of structured ``CodeEdit``s.

The coder emits anchored edits (whole file, named symbol, or line range); this
module resolves anchors with tree-sitter and produces the new file text — the
same routine serves the verifier (virtual apply, nothing touches disk) and the
finalizer (real write after the HITL gate). Reproducible edits are what make
modify/update auditable.
"""
from __future__ import annotations

import re
from pathlib import Path

from .models import AppliedEdit, CodeEdit
from .retrieval.tree_sitter import language_for_file, parse_source

_RANGE_RE = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*$")


class EditError(ValueError):
    """Anchor could not be resolved / edit is inconsistent."""


def _resolve_anchor(original: str, edit: CodeEdit) -> tuple[int, int]:
    """Return (start_line, end_line) 1-based inclusive for the anchor."""
    anchor = (edit.anchor or "").strip()
    if not anchor:
        return 1, original.count("\n") + 1

    m = _RANGE_RE.match(anchor)
    if m:
        start, end = int(m.group(1)), int(m.group(2))
        n = original.count("\n") + 1
        if not (1 <= start <= end <= max(n, 1)):
            raise EditError(f"line range {anchor!r} outside file (1-{n})")
        return start, end

    # Symbol anchor: find by (qualified) name via tree-sitter.
    lang = language_for_file(edit.path)
    if lang:
        parsed = parse_source(original, lang, edit.path)
        want = anchor.split()[-1]  # accept 'class UserService' or 'UserService'
        for sym in parsed.symbols:
            if sym.name == want or sym.name == anchor:
                return sym.start_line, sym.end_line
    # Fallback: first line containing the anchor text verbatim.
    for i, line in enumerate(original.splitlines(), start=1):
        if anchor in line:
            return i, i
    raise EditError(f"anchor {anchor!r} not found in {edit.path}")


def apply_edit_to_text(original: str, edit: CodeEdit) -> str:
    """Pure function: original file text + edit → new file text."""
    lines = original.splitlines(keepends=True)
    if original and not original.endswith("\n"):
        # normalise so slicing by line is uniform
        lines[-1] = lines[-1] + "\n"

    content = edit.content
    if content and not content.endswith("\n"):
        content += "\n"

    if edit.action == "create":
        return content

    if edit.action == "replace":
        if not (edit.anchor or "").strip():
            return content  # whole-file replace
        start, end = _resolve_anchor(original, edit)
        return "".join(lines[: start - 1]) + content + "".join(lines[end:])

    if edit.action == "insert":
        if not (edit.anchor or "").strip():
            return original + ("" if original.endswith("\n") or not original else "\n") + content
        _, end = _resolve_anchor(original, edit)
        return "".join(lines[:end]) + content + "".join(lines[end:])

    if edit.action == "delete":
        start, end = _resolve_anchor(original, edit)
        return "".join(lines[: start - 1]) + "".join(lines[end:])

    raise EditError(f"unknown edit action {edit.action!r}")


def materialize(edits: list[CodeEdit], root: Path | str = ".") -> dict[str, str]:
    """Virtually apply all edits → ``{path: new_full_text}``.

    Reads current file contents from disk; multiple edits to one file compose
    in order. Raises :class:`EditError` on unresolvable anchors so the verifier
    catches bad edits *before* anything is written.
    """
    root = Path(root)
    result: dict[str, str] = {}
    for edit in edits:
        p = (root / edit.path) if not Path(edit.path).is_absolute() else Path(edit.path)
        key = str(p)
        if key in result:
            current = result[key]
        elif p.exists():
            current = p.read_text(encoding="utf-8", errors="replace")
        else:
            if edit.action != "create":
                raise EditError(f"{edit.path}: file does not exist for action {edit.action!r}")
            current = ""
        result[key] = apply_edit_to_text(current, edit)
    return result


def unified_diffs(files: dict[str, str]) -> dict[str, str]:
    """Unified diff per file: current on-disk content vs the proposed content.

    New files diff against empty. Powers the approval gate, CLI output, the
    Electron diff view and the evidence package.
    """
    import difflib

    out: dict[str, str] = {}
    for path_str, new_text in files.items():
        p = Path(path_str)
        old_text = ""
        if p.exists():
            try:
                old_text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass
        diff = "".join(difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=f"a/{p.name}", tofile=f"b/{p.name}", n=3,
        ))
        out[path_str] = diff
    return out


def write_files(files: dict[str, str], allowed_roots: list[Path]) -> list[AppliedEdit]:
    """Write materialized files to disk, enforcing the writable-path policy."""
    applied: list[AppliedEdit] = []
    resolved_roots = [r.resolve() for r in allowed_roots]

    def permitted(p: Path) -> bool:
        if not resolved_roots:
            return False
        rp = p.resolve()
        for root in resolved_roots:
            if rp == root or root in rp.parents:
                return True
        return False

    for path_str, text in files.items():
        p = Path(path_str)
        entry = AppliedEdit(action="replace" if p.exists() else "create", path=path_str)
        if not permitted(p):
            entry.error = "outside writable paths — blocked by policy"
            applied.append(entry)
            continue
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            data = text.encode("utf-8")
            p.write_bytes(data)
            entry.applied = True
            entry.bytes_written = len(data)
        except OSError as e:
            entry.error = str(e)
        applied.append(entry)
    return applied
