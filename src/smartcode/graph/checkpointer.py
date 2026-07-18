"""Durable session ledger: sqlite checkpointer at ``.smartcode/sessions.db``.

Every super-step of the graph is journaled, making runs resumable and
auditable (Harness pattern #05). Disable with ``SMARTCODE_ENABLE_CHECKPOINTER=false``.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from ..config import Settings


def open_checkpointer(settings: Settings):
    """Return a ``SqliteSaver`` or None when checkpointing is disabled."""
    if not settings.enable_checkpointer:
        return None
    from langgraph.checkpoint.sqlite import SqliteSaver

    settings.ensure_dirs()
    conn = sqlite3.connect(str(settings.session_db_path), check_same_thread=False)
    return SqliteSaver(conn)
