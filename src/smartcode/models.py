"""Typed domain contracts — the 'code-owned' backbone of the agent.

Every node in the LangGraph operates on these Pydantic models rather than free-form
text. This implements the *Task Contract* and *Context Contract* patterns from the
Harness / Context-engineering reference docs: guarantees live in schemas and
validation artefacts, not in prompts.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Intent & task
# ---------------------------------------------------------------------------
Intent = Literal["new", "modify", "review"]


class RiskTier(str, Enum):
    """Risk classification drives the write-gate policy (Harness pattern #13)."""

    LOW = "low"        # auto-apply edits
    MEDIUM = "medium"  # prompt user before writing
    HIGH = "high"      # require explicit approval; block if unscoped


class TaskContract(BaseModel):
    """Versioned work contract (Harness pattern #01: Task Contract).

    Compile a free-form request into a goal, constraints, allowed tools/sources,
    acceptance criteria, output schema, risk tier and budget. The agent executes
    *against* the contract; completion requires acceptance to pass.
    """

    objective: str = Field(..., description="the concrete goal of the work")
    intent: Intent
    language: Optional[str] = Field(None, description="target language id, e.g. 'python'")
    framework: Optional[str] = Field(None, description="target framework id, e.g. 'fastapi'")
    writable_paths: list[Path] = Field(
        default_factory=list,
        description="paths the agent is permitted to create/modify; empty + high-risk => refuse",
    )
    acceptance: list[str] = Field(
        default_factory=list,
        description="machine- or human-checkable completion criteria",
    )
    risk_tier: RiskTier = RiskTier.MEDIUM
    max_iterations: int = Field(default=4, ge=1, le=12)
    notes: str = ""
    version: int = 1

    def validate_contract(self) -> None:
        """Deterministic contract validation — fail fast before any model call."""
        if not self.objective.strip():
            raise ValueError("TaskContract.objective must be non-empty.")
        if not self.acceptance:
            raise ValueError("At least one acceptance criterion is required.")
        if self.risk_tier == RiskTier.HIGH and not self.writable_paths:
            raise ValueError("High-risk tasks require an explicit writable scope or must be refused.")
        if self.intent == "modify" and not self.writable_paths:
            raise ValueError("modify intent requires at least one writable target path.")


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------
class Step(BaseModel):
    """One bounded unit of work inside a plan."""

    description: str
    target: Optional[str] = Field(None, description="file or symbol this step touches")
    rationale: str = ""


class Plan(BaseModel):
    """Output of the planner node — adaptive, not an immutable giant plan."""

    steps: list[Step] = Field(default_factory=list)
    approach: str = Field("", description="short prose summary of the chosen approach")
    open_questions: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Edits — structured, deterministic, not raw prose
# ---------------------------------------------------------------------------
EditAction = Literal["create", "replace", "insert", "delete"]


class CodeEdit(BaseModel):
    """A single reproducible edit. The coder emits these; the applier executes them.

    Working with structured edits (not whole-file blobs) keeps modify/update
    reproducible and auditable, and matches the *Structured Scratchpad* /
    *Evidence Package* patterns.
    """

    action: EditAction
    path: str
    anchor: Optional[str] = Field(
        None, description="symbol/range the edit anchors to (e.g. 'class UserService' or '12-18')"
    )
    content: str = Field("", description="new content for create/replace/insert")
    summary: str = ""


class EditSet(BaseModel):
    """The coder's full structured answer — the unit the verifier consumes."""

    edits: list[CodeEdit] = Field(default_factory=list)
    notes: str = ""


class IntentOut(BaseModel):
    """Classifier output contract."""

    intent: Intent


# ---------------------------------------------------------------------------
# Retrieval evidence
# ---------------------------------------------------------------------------
class Evidence(BaseModel):
    """A retrieved code/document chunk with provenance (Context engineering #10)."""

    path: str
    language: Optional[str] = None
    symbol: Optional[str] = None
    content: str
    source: str = "repo"          # 'repo' | 'skill' | 'contract'
    authority: str = "project"    # 'system' > 'org' > 'project' > 'retrieved'
    score: float = 0.0

    def approx_tokens(self) -> int:
        # rough 1 token ≈ 4 chars heuristic for budgeting
        return max(1, len(self.content) // 4)


# ---------------------------------------------------------------------------
# Verification — the deterministic sensor (Harness pattern #07)
# ---------------------------------------------------------------------------
class CheckResult(BaseModel):
    name: str
    passed: bool
    detail: str = ""


class VerifyResult(BaseModel):
    """Output of the verifier node. Drives the evaluator-optimizer branch."""

    parsed_ok: bool = True
    checks: list[CheckResult] = Field(default_factory=list)
    lint_ok: Optional[bool] = None
    tests_ok: Optional[bool] = None
    overall_ok: bool = False
    summary: str = ""

    @property
    def all_passed(self) -> bool:
        if not self.overall_ok:
            return False
        if self.lint_ok is False or self.tests_ok is False:
            return False
        return all(c.passed for c in self.checks)


# ---------------------------------------------------------------------------
# Critique — the inferential reviewer / judge (Harness #08, Critic pattern)
# ---------------------------------------------------------------------------
class Finding(BaseModel):
    severity: Literal["blocker", "major", "minor", "nit"]
    message: str
    location: Optional[str] = None
    suggestion: Optional[str] = None


class Critique(BaseModel):
    """Judge verdict on the generated code."""

    findings: list[Finding] = Field(default_factory=list)
    score: float = Field(0.0, ge=0.0, le=1.0, description="overall quality score")
    satisfies_acceptance: bool = False
    revise: bool = False
    rationale: str = ""

    @property
    def has_blocker(self) -> bool:
        return any(f.severity == "blocker" for f in self.findings)


# ---------------------------------------------------------------------------
# HITL + Evidence Package
# ---------------------------------------------------------------------------
HITLDecision = Literal["pending", "approved", "rejected", "skipped"]


class AppliedEdit(BaseModel):
    """A code edit as actually applied to disk — part of the evidence package."""

    action: EditAction
    path: str
    bytes_written: int = 0
    applied: bool = False
    error: Optional[str] = None


class EvidencePackage(BaseModel):
    """Final, auditable artefact (Harness pattern #19: Evidence Package).

    Captures what was done, why, what passed verification, and what was written.
    Persisted alongside the session ledger so any run is reconstructable.
    """

    task: TaskContract
    plan: Optional[Plan] = None
    edits: list[CodeEdit] = Field(default_factory=list)
    applied: list[AppliedEdit] = Field(default_factory=list)
    diffs: dict[str, str] = Field(
        default_factory=dict,
        description="unified diff per file (old disk content vs proposed content)",
    )
    verify: Optional[VerifyResult] = None
    critique: Optional[Critique] = None
    revisions: int = 0
    completed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: Literal["success", "best_effort", "rejected", "review_only"] = "success"


# ---------------------------------------------------------------------------
# Structured scratchpad (Context engineering #03)
# ---------------------------------------------------------------------------
class StructuredScratchpad(BaseModel):
    """Compact working memory: plans/findings/decisions live outside the chat log."""

    goal: str = ""
    observations: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    failed_approaches: list[str] = Field(default_factory=list)

    def to_prompt_block(self) -> str:
        lines = ["## Scratchpad"]
        if self.goal:
            lines.append(f"- goal: {self.goal}")
        for obs in self.observations:
            lines.append(f"- observation: {obs}")
        for dec in self.decisions:
            lines.append(f"- decision: {dec}")
        if self.open_questions:
            lines.append("- open questions: " + "; ".join(self.open_questions))
        if self.failed_approaches:
            lines.append("- failed: " + "; ".join(self.failed_approaches))
        return "\n".join(lines) if len(lines) > 1 else ""
