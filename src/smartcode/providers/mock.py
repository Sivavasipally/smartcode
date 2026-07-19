"""Deterministic offline provider for tests and demos.

The mock inspects the conversation for the JSON-schema ``title`` injected by
``invoke_structured``'s JSON contract and answers with a canned, schema-valid
object. The coder response echoes the target path found in the prompt so the
end-to-end graph genuinely writes/edits files.
"""
from __future__ import annotations

import json
import re
from typing import Any, List, Optional

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from .base import BaseProvider

_PATH_RE = re.compile(r"^TARGET_FILES:\s*(.+)$", re.MULTILINE)
_LANG_RE = re.compile(r"^LANGUAGE:\s*(\w+)$", re.MULTILINE)
_CAND_RE = re.compile(r"^WORKSPACE_CANDIDATES:\s*(.+)$", re.MULTILINE)

_SNIPPETS = {
    "python": "def solve(x):\n    \"\"\"Deterministic mock implementation.\"\"\"\n    return x\n",
    "javascript": "function solve(x) {\n  return x;\n}\n\nmodule.exports = { solve };\n",
    "typescript": "export function solve(x: number): number {\n  return x;\n}\n",
    "go": "package main\n\nfunc solve(x int) int {\n\treturn x\n}\n",
}


class MockChatModel(BaseChatModel):
    """Rule-based stand-in that satisfies every role's output contract."""

    @property
    def _llm_type(self) -> str:
        return "smartcode-mock"

    def _reply(self, text: str) -> str:
        def has(title: str) -> bool:
            return f'"title": "{title}"' in text or f'"title":"{title}"' in text

        if has("IntentOut"):
            return json.dumps({"intent": "new"})
        if has("ChangeProposal"):
            m = _CAND_RE.search(text)
            first = m.group(1).split(",")[0].strip() if m else "src/main.py"
            if re.search(r"^Intent:\s*new", text, re.MULTILINE):
                # place the new file next to the top candidate, repo-conventional
                folder = first.rsplit("/", 1)[0] if "/" in first else "src"
                return json.dumps({"targets": [{"path": f"{folder}/mock_new.py",
                                                "action": "create",
                                                "reason": f"new module beside {first} (mock)"}],
                                   "rationale": "mock create proposal",
                                   "open_questions": []})
            return json.dumps({"targets": [{"path": first, "action": "modify",
                                            "reason": "top-ranked candidate (mock)"}],
                               "rationale": "mock proposal", "open_questions": []})
        if has("Plan"):
            return json.dumps({
                "approach": "Direct single-step implementation (mock).",
                "steps": [{"description": "Implement the requested change",
                           "target": None, "rationale": "smallest correct step"}],
                "open_questions": [],
            })
        if has("EditSet"):
            m = _PATH_RE.search(text)
            path = m.group(1).split(",")[0].strip() if m else "generated/mock_output.py"
            lm = _LANG_RE.search(text)
            lang = lm.group(1).lower() if lm else "python"
            content = _SNIPPETS.get(lang, _SNIPPETS["python"])
            action = "replace" if "intent: modify" in text else "create"
            return json.dumps({"edits": [{
                "action": action, "path": path, "anchor": None,
                "content": content, "summary": f"mock {action} of {path}",
            }], "notes": "mock edit"})
        if has("Critique"):
            return json.dumps({
                "findings": [], "score": 0.9, "satisfies_acceptance": True,
                "revise": False, "rationale": "mock: acceptance criteria met",
            })
        return json.dumps({"ok": True})

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        text = "\n".join(
            m.content if isinstance(m.content, str) else str(m.content) for m in messages
        )
        msg = AIMessage(content=self._reply(text))
        return ChatResult(generations=[ChatGeneration(message=msg)])


class MockProvider(BaseProvider):
    id = "mock"
    native_structured = False

    def chat_model(self) -> BaseChatModel:
        return MockChatModel()

    def available(self) -> tuple[bool, str]:
        return True, "always available (offline stub)"
