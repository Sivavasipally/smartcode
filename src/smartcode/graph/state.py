"""Graph state — the durable, checkpointable record of a run.

Everything is stored as plain JSON-serialisable dicts (pydantic ``model_dump``
of the typed contracts in :mod:`smartcode.models`) so the sqlite checkpointer
can persist every step — the *Durable State & Session Ledger* pattern. The
``events`` field is an append-only reducer: each node contributes trace events
that survive checkpoint/resume.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class State(TypedDict, total=False):
    # contract & routing
    task: dict            # TaskContract.model_dump
    intent: str
    error: str            # fatal condition → route straight to finalize

    # context plane
    repo_map: str
    retrieved: list[dict]  # Evidence dumps (post budget/rerank)
    skill: str
    scratchpad: dict       # StructuredScratchpad dump

    # plan-execute-verify plane
    plan: dict             # Plan dump
    edits: list[dict]      # CodeEdit dumps (latest coder attempt)
    files: dict            # {path: new_full_text} — virtual apply result
    diffs: dict            # {path: unified diff vs disk} — computed by verifier
    verify: dict           # VerifyResult dump
    critique: dict         # Critique dump
    revise_count: int
    feedback: str          # repair feedback for the next coder attempt

    # policy & output plane
    hitl_decision: str
    evidence: dict         # EvidencePackage dump

    # append-only run ledger
    events: Annotated[list[dict[str, Any]], operator.add]
