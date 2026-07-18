"""Rerank-and-Budget + Sufficient Context Gate (context-engineering B5/B6).

Deterministic pipeline: score evidence against the objective (keyword overlap
with a recency/kind prior), dedupe, then greedily pack the best items under the
token budget. No embeddings needed for v1 — symbol names + objective words are
a strong signal for code tasks, and the whole thing is reproducible.
"""
from __future__ import annotations

import re

from ..models import Evidence

_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]+")


def _words(text: str) -> set[str]:
    out = set()
    for w in _WORD_RE.findall(text.lower()):
        out.add(w)
        # split snake_case / camelCase-ish fragments for better overlap
        out.update(p for p in re.split(r"_", w) if len(p) > 2)
    return out


def score_evidence(objective: str, evidence: list[Evidence]) -> list[Evidence]:
    """Assign relevance scores in place and return the list sorted best-first."""
    goal = _words(objective)
    for ev in evidence:
        sig = _words((ev.symbol or "") + " " + ev.path)
        body = _words(ev.content[:2000])
        sig_hit = len(goal & sig)
        body_hit = len(goal & body)
        ev.score = sig_hit * 3.0 + body_hit * 1.0
        if ev.source == "skill":       # procedural memory is cheap and broadly useful
            ev.score += 1.0
    return sorted(evidence, key=lambda e: e.score, reverse=True)


def budget_evidence(
    objective: str,
    evidence: list[Evidence],
    token_budget: int,
    *,
    always_keep: int = 1,
) -> tuple[list[Evidence], bool]:
    """Return (selected evidence, sufficient?).

    Greedy pack after rerank + dedupe. ``sufficient`` is False when nothing
    from the repo survived for a task that plainly needs repo context — the
    caller (sufficiency gate) decides whether to halt or degrade.
    """
    ranked = score_evidence(objective, evidence)

    seen: set[tuple[str, str]] = set()
    selected: list[Evidence] = []
    used = 0
    for i, ev in enumerate(ranked):
        key = (ev.path, ev.symbol or "")
        if key in seen:
            continue
        cost = ev.approx_tokens()
        if used + cost > token_budget and i >= always_keep:
            continue
        seen.add(key)
        selected.append(ev)
        used += cost

    sufficient = bool(selected)
    return selected, sufficient


def render_evidence(evidence: list[Evidence]) -> str:
    """Render selected evidence as fenced, provenance-tagged blocks."""
    parts = []
    for ev in evidence:
        head = f"### {ev.path}" + (f" :: {ev.symbol}" if ev.symbol else "")
        parts.append(f"{head}  (source={ev.source})\n```{ev.language or ''}\n{ev.content}\n```")
    return "\n\n".join(parts)
