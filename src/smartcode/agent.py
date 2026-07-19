"""CodeAgent facade — the public entry point over the LangGraph pipeline.

Compiles a user request into a :class:`TaskContract`, runs the graph
(classify → retrieve → plan → code → verify → critique → repair → gate →
finalize) and returns the :class:`EvidencePackage`.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional, Sequence

from .config import Settings, load_settings
from .graph.builder import build_graph
from .graph.checkpointer import open_checkpointer
from .graph.nodes import ApprovalCallback, GraphNodes, ProposalCallback
from .models import EvidencePackage, RiskTier, TaskContract
from .observability import OnEvent, RunLogger
from .providers.registry import get_provider

#: canonical output extension per language id
EXT_BY_LANG = {
    "python": ".py", "javascript": ".js", "typescript": ".ts", "go": ".go",
    "rust": ".rs", "java": ".java", "c": ".c", "cpp": ".cpp",
    "csharp": ".cs", "ruby": ".rb", "php": ".php",
}


class CodeAgent:
    """Generate, modify/update, and review code with any configured provider.

    >>> agent = CodeAgent(provider="mock")
    >>> ev = agent.generate("a slugify helper", language="python",
    ...                     out_path="out/slug.py")
    """

    def __init__(
        self,
        provider: Optional[str] = None,
        settings: Optional[Settings] = None,
        approval_callback: Optional[ApprovalCallback] = None,
        proposal_callback: Optional[ProposalCallback] = None,
        on_event: Optional[OnEvent] = None,
        **overrides: object,
    ):
        if settings is None:
            settings = load_settings(provider=provider, **overrides)
        elif provider:
            settings = settings.model_copy(update={"provider": provider})
        self.settings = settings
        self.approval_callback = approval_callback
        self.proposal_callback = proposal_callback
        self.on_event = on_event

    # ------------------------------------------------------------------ api
    def generate(
        self,
        objective: str,
        *,
        language: Optional[str] = None,
        framework: Optional[str] = None,
        out_path: Optional[str] = None,
        root: Optional[str | Path] = None,
        acceptance: Optional[Sequence[str]] = None,
        risk: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> EvidencePackage:
        """Create new code for ``objective``.

        Three targeting modes, most explicit wins:
        - ``out_path`` given → write exactly there (no proposal round-trip).
        - ``root`` given → the agent scans the codebase under ``root``,
          proposes where the new file(s) belong (conventional folder/name,
          plus any wiring edits to existing files) and pauses at the
          proposal gate for review before generating.
        - neither → legacy fallback ``generated/solution<ext>``.
        """
        kwargs: dict = {}
        if out_path:
            kwargs["writable_paths"] = [Path(out_path)]
        elif root:
            kwargs["writable_paths"] = []
            kwargs["workspace_root"] = Path(root)
        else:
            ext = EXT_BY_LANG.get((language or "python").lower(), ".txt")
            kwargs["writable_paths"] = [Path(f"generated/solution{ext}")]
        task = TaskContract(
            objective=objective,
            intent="new",
            language=language,
            framework=framework,
            acceptance=list(acceptance) if acceptance else [
                "code parses/compiles cleanly",
                f"implements: {objective}",
            ],
            risk_tier=RiskTier(risk or self.settings.default_risk_tier),
            **kwargs,
        )
        return self._run(task, session_id)

    def modify(
        self,
        paths: Sequence[str | Path],
        instruction: str,
        *,
        language: Optional[str] = None,
        framework: Optional[str] = None,
        acceptance: Optional[Sequence[str]] = None,
        risk: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> EvidencePackage:
        """Modify/update the given existing files per ``instruction``."""
        task = TaskContract(
            objective=instruction,
            intent="modify",
            language=language,
            framework=framework,
            writable_paths=[Path(p) for p in paths],
            acceptance=list(acceptance) if acceptance else [
                "existing behaviour preserved except for the requested change",
                f"implements: {instruction}",
            ],
            risk_tier=RiskTier(risk or self.settings.default_risk_tier),
        )
        return self._run(task, session_id)

    def review(
        self,
        paths: Sequence[str | Path],
        *,
        focus: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> EvidencePackage:
        """Review the given files; reports findings, never writes."""
        objective = focus or "review this code for correctness, safety and maintainability"
        task = TaskContract(
            objective=objective,
            intent="review",
            writable_paths=[Path(p) for p in paths],
            acceptance=["all significant defects reported with severity"],
            risk_tier=RiskTier.LOW,
        )
        return self._run(task, session_id)

    def workspace(
        self,
        objective: str,
        root: str | Path,
        *,
        language: Optional[str] = None,
        framework: Optional[str] = None,
        acceptance: Optional[Sequence[str]] = None,
        risk: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> EvidencePackage:
        """Folder-scale run over a directory that may hold multiple repos.

        The agent scans every repo under ``root``, proposes which files to
        change (create/modify + reason), pauses for review via
        ``proposal_callback`` — approve / narrow the set / send suggestions
        for a re-proposal — and only then plans, codes, verifies and (after
        the usual diff-gated write approval) applies the change.
        """
        task = TaskContract(
            objective=objective,
            intent="modify",
            language=language,
            framework=framework,
            workspace_root=Path(root),
            writable_paths=[],
            acceptance=list(acceptance) if acceptance else [
                "only the approved target files are changed",
                f"implements: {objective}",
            ],
            risk_tier=RiskTier(risk or self.settings.default_risk_tier),
        )
        return self._run(task, session_id)

    # ------------------------------------------------------------------ core
    def _run(self, task: TaskContract, session_id: Optional[str]) -> EvidencePackage:
        settings = self.settings
        settings.ensure_dirs()
        run_id = session_id or uuid.uuid4().hex[:12]

        logger = RunLogger(settings.data_dir, run_id, on_event=self.on_event)
        provider = get_provider(settings.provider, settings)
        nodes = GraphNodes(settings, provider, logger,
                           approval_callback=self.approval_callback,
                           proposal_callback=self.proposal_callback)
        checkpointer = open_checkpointer(settings)
        graph = build_graph(nodes, settings, checkpointer=checkpointer)

        config = {"configurable": {"thread_id": run_id}, "recursion_limit": 80}
        try:
            final = graph.invoke(
                {"task": task.model_dump(mode="json"), "intent": task.intent,
                 "revise_count": 0, "events": []},
                config,
            )
        finally:
            logger.close()

        if "evidence" not in final:  # defensive: finalize always runs, but never crash the caller
            return EvidencePackage(task=task, status="rejected")
        return EvidencePackage.model_validate(final["evidence"])


# ---------------------------------------------------------------------------
# Module-level conveniences
# ---------------------------------------------------------------------------
def generate(objective: str, **kwargs) -> EvidencePackage:
    provider = kwargs.pop("provider", None)
    return CodeAgent(provider=provider).generate(objective, **kwargs)


def modify(paths: Sequence[str | Path], instruction: str, **kwargs) -> EvidencePackage:
    provider = kwargs.pop("provider", None)
    return CodeAgent(provider=provider).modify(paths, instruction, **kwargs)


def review(paths: Sequence[str | Path], **kwargs) -> EvidencePackage:
    provider = kwargs.pop("provider", None)
    return CodeAgent(provider=provider).review(paths, **kwargs)
