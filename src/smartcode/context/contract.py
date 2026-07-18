"""Context Contract (context-engineering pattern A2).

A declarative statement of what a role node *requires* in context, what is
*forbidden*, and how sufficiency is judged before the model is called. The
retriever/sufficiency gate checks the contract deterministically — a model is
never invoked on context we already know is inadequate.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..models import Evidence


@dataclass
class ContextContract:
    role: str
    #: sources that MUST be present for this role to run (e.g. 'repo' for modify)
    required_sources: tuple[str, ...] = ()
    #: sources that must never reach this role's prompt
    forbidden_sources: tuple[str, ...] = ()
    #: minimum evidence items for sufficiency
    min_items: int = 0
    notes: str = ""
    violations: list[str] = field(default_factory=list)

    def check(self, evidence: list[Evidence]) -> bool:
        """Deterministic sufficiency gate. Populates ``violations`` on failure."""
        self.violations = []
        present = {e.source for e in evidence}
        for src in self.required_sources:
            if src not in present:
                self.violations.append(f"required source {src!r} missing from context")
        for e in evidence:
            if e.source in self.forbidden_sources:
                self.violations.append(f"forbidden source {e.source!r} present ({e.path})")
        if len(evidence) < self.min_items:
            self.violations.append(
                f"insufficient context: {len(evidence)} item(s), need >= {self.min_items}"
            )
        return not self.violations


#: Contracts per role. 'modify' and 'review' cannot proceed without repo evidence.
CODER_NEW = ContextContract(role="coder:new")
CODER_MODIFY = ContextContract(role="coder:modify", required_sources=("repo",), min_items=1)
CRITIC_REVIEW = ContextContract(role="critic:review", required_sources=("repo",), min_items=1)


def contract_for(role: str, intent: str) -> ContextContract:
    if intent == "modify" and role == "coder":
        return ContextContract(role="coder:modify", required_sources=("repo",), min_items=1)
    if intent == "review":
        return ContextContract(role="critic:review", required_sources=("repo",), min_items=1)
    return ContextContract(role=f"{role}:{intent}")
