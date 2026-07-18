"""Supervisor routing (Harness pattern #17) — all control flow in one place.

Pure functions over ``State``; no LLM calls here. The topology:

    classify ─┬─ new ───────────→ planner → coder → verifier ─┬ ok → critic
              ├─ modify → retriever ↗                          └ fail → repair → coder
              └─ review → retriever → critic
    critic ── revise (budget left) → repair
           └─ done/review → hitl_gate|finalize
"""
from __future__ import annotations

from ..config import Settings
from .state import State


def route_after_classify(state: State) -> str:
    if state.get("error"):
        return "finalize"
    intent = state.get("intent", "new")
    return "planner" if intent == "new" else "retriever"


def route_after_retrieve(state: State) -> str:
    if state.get("error"):
        return "finalize"
    return "critic" if state.get("intent") == "review" else "planner"


def make_route_after_verify(settings: Settings):
    def route_after_verify(state: State) -> str:
        if state.get("error"):
            return "finalize"
        verify = state.get("verify") or {}
        if verify.get("overall_ok"):
            return "critic"
        if state.get("revise_count", 0) < settings.max_revisions:
            return "repair"
        return "critic"  # out of budget: let the judge record the failure honestly
    return route_after_verify


def make_route_after_critic(settings: Settings):
    def route_after_critic(state: State) -> str:
        if state.get("intent") == "review":
            return "finalize"
        critique = state.get("critique") or {}
        if critique.get("revise") and state.get("revise_count", 0) < settings.max_revisions:
            return "repair"
        return "hitl_gate"
    return route_after_critic
