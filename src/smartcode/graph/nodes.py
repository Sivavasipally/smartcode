"""Graph nodes: classify → retrieve → plan → code → verify → critique →
repair → hitl_gate → finalize.

Each node is a method on :class:`GraphNodes`, reads/writes only typed
contracts (pydantic ↔ dict at the state boundary), and appends trace events.
LLM calls always go through ``invoke_structured`` so every role has an
enforceable output contract regardless of provider.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from ..config import LANG_BY_EXT, Settings
from ..context.authority import build_system_prompt
from ..context.compaction import compact_scratchpad
from ..context.contract import contract_for
from ..editing import EditError, materialize, write_files
from ..models import (
    Critique,
    EditSet,
    Evidence,
    EvidencePackage,
    IntentOut,
    Plan,
    StructuredScratchpad,
    TaskContract,
    VerifyResult,
)
from ..observability import RunLogger
from ..prompts.roles import render_classifier, render_coder, render_critic, render_planner
from ..providers.base import BaseProvider, StructuredOutputError, invoke_structured
from ..retrieval.context_budget import budget_evidence, render_evidence
from ..retrieval.repo_map import build_repo_map
from ..retrieval.tree_sitter import parse_file
from ..skills.registry import skill_for_task
from ..verify.ast_checks import check_files
from ..verify.linters import run_linters
from ..verify.tests import run_tests
from .state import State

#: (task, edits, files) -> approve?
ApprovalCallback = Callable[[TaskContract, list[dict], dict], bool]

#: Keep whole files in context only below this size; larger files go symbol-by-symbol.
_WHOLE_FILE_LINES = 120


class GraphNodes:
    def __init__(
        self,
        settings: Settings,
        provider: BaseProvider,
        logger: RunLogger,
        approval_callback: Optional[ApprovalCallback] = None,
    ):
        self.settings = settings
        self.provider = provider
        self.logger = logger
        self.approval_callback = approval_callback
        self._llm = None

    @property
    def llm(self):
        if self._llm is None:
            self._llm = self.provider.chat_model()
        return self._llm

    def _structured(self, messages, schema):
        return invoke_structured(
            self.llm, messages, schema, native=self.provider.native_structured
        )

    def _task(self, state: State) -> TaskContract:
        return TaskContract.model_validate(state["task"])

    def _pad(self, state: State) -> StructuredScratchpad:
        return StructuredScratchpad.model_validate(state.get("scratchpad") or {})

    # ------------------------------------------------------------------ nodes
    def classify_intent(self, state: State) -> State:
        task = self._task(state)
        intent = state.get("intent") or task.intent

        # LLM classification only when the caller didn't declare an intent.
        if not intent:
            targets = [str(p) for p in task.writable_paths]
            out = self._structured(
                [HumanMessage(content=render_classifier(task.objective, targets))],
                IntentOut,
            )
            intent = out.intent

        # Infer language from target file extensions when unset.
        if not task.language:
            for p in task.writable_paths:
                lang = LANG_BY_EXT.get(Path(p).suffix.lower())
                if lang:
                    task.language = lang
                    break

        skill = skill_for_task(task.language, task.framework,
                               data_dir=self.settings.data_dir)
        pad = StructuredScratchpad(goal=task.objective)

        try:
            task.intent = intent  # type: ignore[assignment]
            task.validate_contract()
        except ValueError as e:
            ev = self.logger.emit("classify_intent", f"contract invalid: {e}")
            return {"intent": intent, "error": f"invalid task contract: {e}",
                    "events": [ev]}

        ev = self.logger.emit("classify_intent", f"intent={intent} lang={task.language} "
                              f"framework={task.framework or '-'}")
        return {"intent": intent, "task": task.model_dump(mode="json"),
                "skill": skill, "scratchpad": pad.model_dump(), "events": [ev]}

    def retriever(self, state: State) -> State:
        """Just-in-time context: parse targets → symbol evidence → rerank+budget."""
        task = self._task(state)
        targets = [Path(p) for p in task.writable_paths]

        evidence: list[Evidence] = []
        missing: list[str] = []
        for target in targets:
            parsed = parse_file(target)
            if not parsed.ok:
                missing.append(f"{target}: {parsed.error}")
                continue
            text = parsed.source.decode("utf-8", "replace")
            if parsed.n_lines <= _WHOLE_FILE_LINES or not parsed.symbols:
                evidence.append(Evidence(path=str(target), language=parsed.language,
                                         content=text, source="repo"))
            else:
                for sym in parsed.symbols:
                    evidence.append(Evidence(
                        path=str(target), language=parsed.language,
                        symbol=sym.name, content=sym.body, source="repo",
                    ))

        selected, _ = budget_evidence(task.objective, evidence,
                                      self.settings.context_token_budget)

        # Sufficient-context gate: don't let a coder hallucinate over nothing.
        contract = contract_for("coder", task.intent)
        if not contract.check(selected):
            detail = "; ".join(contract.violations + missing)
            ev = self.logger.emit("retriever", f"insufficient context: {detail}")
            return {"error": f"insufficient context: {detail}", "events": [ev]}

        root = Path.cwd()
        repo_map = build_repo_map(root if root.is_dir() else targets[0], focus=targets)

        ev = self.logger.emit(
            "retriever",
            f"{len(selected)}/{len(evidence)} evidence item(s) within budget",
            paths=[e.path for e in selected],
        )
        return {"retrieved": [e.model_dump() for e in selected],
                "repo_map": repo_map, "events": [ev]}

    def planner(self, state: State) -> State:
        task = self._task(state)
        retrieved = [Evidence.model_validate(e) for e in state.get("retrieved", [])]
        system = build_system_prompt(
            task,
            skill=state.get("skill", ""),
            retrieved=render_evidence(retrieved),
            scratchpad=self._pad(state),
            extra=("## Repo map\n" + state["repo_map"]) if state.get("repo_map") else "",
        )
        try:
            plan = self._structured(
                [SystemMessage(content=system),
                 HumanMessage(content=render_planner(task, self.settings.max_plan_steps))],
                Plan,
            )
        except StructuredOutputError as e:
            ev = self.logger.emit("planner", f"failed: {e}")
            return {"error": f"planner failed: {e}", "events": [ev]}

        plan.steps = plan.steps[: self.settings.max_plan_steps]
        ev = self.logger.emit("planner", f"{len(plan.steps)} step(s): {plan.approach[:120]}",
                              approach=plan.approach,
                              steps=[s.description for s in plan.steps],
                              open_questions=plan.open_questions)
        return {"plan": plan.model_dump(), "events": [ev]}

    def coder(self, state: State) -> State:
        task = self._task(state)
        plan = Plan.model_validate(state.get("plan") or {})
        retrieved = [Evidence.model_validate(e) for e in state.get("retrieved", [])]
        system = build_system_prompt(
            task,
            skill=state.get("skill", ""),
            retrieved=render_evidence(retrieved),
            scratchpad=self._pad(state),
        )
        # Small models can't reliably emit code inside JSON strings: try the
        # fence path first for them (single-target only), JSON as the backstop.
        edit_set = None
        if self.provider.small_model and len(task.writable_paths) == 1:
            edit_set = self._coder_fence_fallback(task, plan, state)
            if edit_set:
                self.logger.emit("coder", "small model: code-fence path used")
        if edit_set is None:
            try:
                edit_set = self._structured(
                    [SystemMessage(content=system),
                     HumanMessage(content=render_coder(task, plan,
                                                       feedback=state.get("feedback", "")))],
                    EditSet,
                )
            except StructuredOutputError as e:
                edit_set = self._coder_fence_fallback(task, plan, state)
                if edit_set is None:
                    ev = self.logger.emit("coder", f"failed: {e}")
                    return {"error": f"coder failed: {e}", "events": [ev]}
                self.logger.emit("coder", "JSON contract failed; code-fence fallback used")

        if not edit_set.edits:
            ev = self.logger.emit("coder", "model returned zero edits")
            return {"error": "coder produced no edits", "events": [ev]}

        ev = self.logger.emit(
            "coder", f"{len(edit_set.edits)} edit(s)",
            edits=[f"{e.action} {e.path}" + (f" @{e.anchor}" if e.anchor else "")
                   for e in edit_set.edits],
        )
        return {"edits": [e.model_dump() for e in edit_set.edits],
                "feedback": "", "events": [ev]}

    def _coder_fence_fallback(self, task: TaskContract, plan: Plan,
                              state: State) -> Optional[EditSet]:
        """Whole-file write via a plain code fence, for models that can't emit
        code-inside-JSON reliably. Only sound for a single target file."""
        from ..providers.base import extract_code_fence

        if len(task.writable_paths) != 1:
            return None
        target = Path(task.writable_paths[0])

        retrieved = [Evidence.model_validate(e) for e in state.get("retrieved", [])]
        from ..retrieval.context_budget import render_evidence as _render
        system = build_system_prompt(task, skill=state.get("skill", ""),
                                     retrieved=_render(retrieved),
                                     scratchpad=self._pad(state))
        feedback = state.get("feedback", "")
        prompt = (
            f"Write the COMPLETE content of the file `{target}` that fulfils the "
            f"objective: {task.objective}\n"
            f"Approach: {plan.approach}\n"
            + (f"Fix these issues from the previous attempt:\n{feedback}\n" if feedback else "")
            + "Reply with ONLY one fenced code block containing the entire file — "
              "no explanation before or after."
        )
        reply = self.llm.invoke([SystemMessage(content=system),
                                 HumanMessage(content=prompt)])
        text = reply.content if isinstance(reply.content, str) else str(reply.content)
        code = extract_code_fence(text)
        if not code:
            return None
        from ..models import CodeEdit
        action = "replace" if target.exists() else "create"
        return EditSet(edits=[CodeEdit(
            action=action, path=str(target), anchor=None, content=code,
            summary=f"whole-file {action} (code-fence fallback)",
        )], notes="code-fence fallback")

    def verifier(self, state: State) -> State:
        """Deterministic sensor: virtual apply → AST checks → linters → tests."""
        from ..models import CodeEdit
        edits = [CodeEdit.model_validate(e) for e in state.get("edits", [])]

        try:
            files = materialize(edits)
        except EditError as e:
            result = VerifyResult(parsed_ok=False, overall_ok=False,
                                  summary=f"edit application failed: {e}")
            ev = self.logger.emit("verifier", result.summary)
            return {"verify": result.model_dump(), "files": {}, "events": [ev]}

        result = check_files(files)

        if result.overall_ok and self.settings.run_linters:
            lint_ok, lint_detail = run_linters(files)
            result.lint_ok = lint_ok
            if lint_ok is False:
                result.overall_ok = False
                result.summary = f"lint failures: {lint_detail}"

        if result.overall_ok and self.settings.run_tests and self.settings.test_command:
            tests_ok, tests_detail = run_tests(self.settings.test_command)
            result.tests_ok = tests_ok
            if tests_ok is False:
                result.overall_ok = False
                result.summary = f"test failures: {tests_detail[:800]}"

        ev = self.logger.emit(
            "verifier",
            "PASS" if result.overall_ok else f"FAIL: {result.summary[:200]}",
            ok=result.overall_ok,
            summary=result.summary,
            lint_ok=result.lint_ok,
            tests_ok=result.tests_ok,
            checks=[{"name": c.name, "passed": c.passed, "detail": c.detail}
                    for c in result.checks],
        )
        return {"verify": result.model_dump(), "files": files, "events": [ev]}

    def critic(self, state: State) -> State:
        """Inferential reviewer / LLM-as-judge."""
        task = self._task(state)
        review_only = state.get("intent") == "review"
        verify = VerifyResult.model_validate(state["verify"]) if state.get("verify") else None

        if review_only:
            retrieved = [Evidence.model_validate(e) for e in state.get("retrieved", [])]
            subject = render_evidence(retrieved)
        else:
            subject = json.dumps(state.get("edits", []), indent=1)[:12000]

        system = build_system_prompt(task, skill=state.get("skill", ""),
                                     scratchpad=self._pad(state))
        try:
            critique = self._structured(
                [SystemMessage(content=system),
                 HumanMessage(content=render_critic(
                     task, subject,
                     verify.summary if verify else "not run",
                     review_only=review_only))],
                Critique,
            )
        except StructuredOutputError as e:
            # A dead judge shouldn't kill the run: record and continue un-judged.
            critique = Critique(score=0.0, satisfies_acceptance=False, revise=False,
                                rationale=f"critic unavailable: {e}")

        # The judge may not overrule the deterministic sensor's failure.
        if verify is not None and not verify.overall_ok:
            critique.satisfies_acceptance = False

        ev = self.logger.emit(
            "critic",
            f"score={critique.score:.2f} revise={critique.revise} "
            f"findings={len(critique.findings)}",
            score=critique.score,
            revise=critique.revise,
            satisfies=critique.satisfies_acceptance,
            rationale=critique.rationale,
            findings=[f.model_dump() for f in critique.findings],
        )
        return {"critique": critique.model_dump(), "events": [ev]}

    def repair(self, state: State) -> State:
        """Self-correction: fold failure signals into scratchpad + feedback."""
        pad = self._pad(state)
        parts: list[str] = []

        verify = state.get("verify") or {}
        if verify and not verify.get("overall_ok"):
            parts.append(f"verification: {verify.get('summary', 'failed')}")
            pad.failed_approaches.append(f"attempt {state.get('revise_count', 0) + 1}: "
                                         f"{verify.get('summary', '')[:160]}")
        critique = state.get("critique") or {}
        for f in critique.get("findings", []):
            if f.get("severity") in ("blocker", "major"):
                line = f"{f['severity']}: {f['message']}"
                if f.get("suggestion"):
                    line += f" — suggestion: {f['suggestion']}"
                parts.append(line)
        if critique.get("rationale") and critique.get("revise"):
            pad.observations.append(f"critic: {critique['rationale'][:160]}")

        pad = compact_scratchpad(pad)
        feedback = "\n".join(f"- {p}" for p in parts) or "- previous attempt inadequate"
        count = state.get("revise_count", 0) + 1
        ev = self.logger.emit("repair", f"revision {count}: {len(parts)} issue(s) fed back")
        return {"feedback": feedback, "revise_count": count,
                "scratchpad": pad.model_dump(), "critique": {}, "events": [ev]}

    def hitl_gate(self, state: State) -> State:
        """Risk-tiered write approval (Human Approval Context pattern)."""
        task = self._task(state)
        tier = task.risk_tier.value

        if state.get("intent") == "review":
            decision = "skipped"
        elif tier == "low":
            decision = "approved"
        elif self.approval_callback is not None:
            ok = self.approval_callback(task, state.get("edits", []),
                                        state.get("files", {}))
            decision = "approved" if ok else "rejected"
        elif not self.settings.enable_hitl:
            # No human in the loop by explicit configuration: medium may pass,
            # high never auto-passes.
            decision = "approved" if tier == "medium" else "rejected"
        else:
            decision = "approved" if tier == "medium" else "rejected"

        ev = self.logger.emit("hitl_gate", f"tier={tier} -> {decision}")
        return {"hitl_decision": decision, "events": [ev]}

    def finalize(self, state: State) -> State:
        """Apply approved edits and assemble the Evidence Package."""
        from ..models import CodeEdit
        task = self._task(state)
        edits = [CodeEdit.model_validate(e) for e in state.get("edits", [])]
        verify = VerifyResult.model_validate(state["verify"]) if state.get("verify") else None
        critique = Critique.model_validate(state["critique"]) if state.get("critique") else None
        plan = Plan.model_validate(state["plan"]) if state.get("plan") else None
        decision = state.get("hitl_decision", "skipped")

        applied = []
        if state.get("intent") == "review":
            status = "review_only"
        elif state.get("error"):
            status = "rejected"
        elif decision == "approved" and state.get("files"):
            roots = [Path(p) for p in task.writable_paths] + list(self.settings.writable_roots)
            applied = write_files(state["files"], allowed_roots=roots)
            wrote_all = applied and all(a.applied for a in applied)
            healthy = (verify is None or verify.overall_ok) and \
                      (critique is None or critique.satisfies_acceptance)
            status = "success" if (wrote_all and healthy) else "best_effort"
        elif decision == "rejected":
            status = "rejected"
        else:
            status = "best_effort"

        package = EvidencePackage(
            task=task, plan=plan, edits=edits, applied=applied,
            verify=verify, critique=critique,
            revisions=state.get("revise_count", 0), status=status,
        )
        if state.get("error"):
            package.task.notes = (package.task.notes + "\n" if package.task.notes else "") + \
                f"error: {state['error']}"

        # Persist the evidence package next to the run ledger.
        try:
            runs = self.settings.data_dir / "runs"
            runs.mkdir(parents=True, exist_ok=True)
            stamp = package.completed_at.replace(":", "-").split(".")[0]
            (runs / f"evidence-{stamp}.json").write_text(
                package.model_dump_json(indent=2), encoding="utf-8")
        except OSError:
            pass

        ev = self.logger.emit(
            "finalize",
            f"status={status} written={sum(1 for a in applied if a.applied)}",
            status=status,
            applied=[a.model_dump() for a in applied],
        )
        return {"evidence": package.model_dump(mode="json"), "events": [ev]}
