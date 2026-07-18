"""Structured run logging: JSONL ledger + optional live callback.

Each node emits typed events. They land in three places: the graph state's
append-only ``events`` reducer (checkpointed), a per-run ``.jsonl`` file under
``.smartcode/runs/``, and an optional ``on_event`` callback the CLI uses for
live Rich output.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

OnEvent = Callable[[dict], None]


class RunLogger:
    def __init__(self, data_dir: Path, run_id: str,
                 on_event: Optional[OnEvent] = None, enabled: bool = True):
        self.on_event = on_event
        self._file = None
        if enabled:
            runs = data_dir / "runs"
            try:
                runs.mkdir(parents=True, exist_ok=True)
                self._file = (runs / f"{run_id}.jsonl").open("a", encoding="utf-8")
            except OSError:
                self._file = None
        self._t0 = time.monotonic()

    def emit(self, node: str, message: str, **data: Any) -> dict:
        event = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "elapsed_s": round(time.monotonic() - self._t0, 2),
            "node": node,
            "message": message,
            **data,
        }
        if self._file:
            try:
                self._file.write(json.dumps(event, default=str) + "\n")
                self._file.flush()
            except OSError:
                pass
        if self.on_event:
            try:
                self.on_event(event)
            except Exception:
                pass
        return event

    def close(self) -> None:
        if self._file:
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None
