"""Loss-aware compaction + sliding recency window (context-engineering C1/C2).

The scratchpad is the agent's working memory across revision loops. Older
observations are folded into a compact summary line instead of being dropped
silently — decisions and failed approaches are always kept verbatim because
losing them causes repeated mistakes (the classic compaction failure mode).
"""
from __future__ import annotations

from ..models import StructuredScratchpad

#: Keep at most this many recent observations verbatim.
_WINDOW = 6
_MAX_FAILED = 8


def compact_scratchpad(pad: StructuredScratchpad) -> StructuredScratchpad:
    """Return a size-bounded copy of the scratchpad, newest entries preserved."""
    pad = pad.model_copy(deep=True)

    if len(pad.observations) > _WINDOW:
        dropped = pad.observations[:-_WINDOW]
        kept = pad.observations[-_WINDOW:]
        summary = f"[compacted] {len(dropped)} earlier observation(s) elided; themes: " + \
            "; ".join(o[:60] for o in dropped[-2:])
        pad.observations = [summary, *kept]

    # Failed approaches are high-value negative knowledge — trim only extremes.
    if len(pad.failed_approaches) > _MAX_FAILED:
        pad.failed_approaches = pad.failed_approaches[-_MAX_FAILED:]

    # De-duplicate while preserving order.
    for attr in ("observations", "decisions", "open_questions", "failed_approaches"):
        seen: set[str] = set()
        unique = []
        for item in getattr(pad, attr):
            if item not in seen:
                seen.add(item)
                unique.append(item)
        setattr(pad, attr, unique)
    return pad
