"""Provider abstraction + the schema-first *Output Contract* helper.

Every provider yields a LangChain ``BaseChatModel``. Structured output is
centralised in :func:`invoke_structured`, which prefers the provider's native
structured-output path and falls back to a JSON contract with pydantic
validation and bounded repair retries — the *Output Contract* pattern. This is
what lets a 1.5B local SLM and Claude share the exact same graph.
"""
from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from typing import Any, Sequence, Type, TypeVar

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage
from pydantic import BaseModel, ValidationError

from ..config import Settings

TModel = TypeVar("TModel", bound=BaseModel)


class ProviderError(RuntimeError):
    """Provider unavailable / misconfigured (missing key, missing deps, ...)."""


class StructuredOutputError(RuntimeError):
    """The model failed to produce schema-valid output within the retry budget."""


class BaseProvider(ABC):
    """One LLM backend. Subclasses declare availability and build the chat model."""

    id: str = "base"
    #: True when the backend supports langchain native structured output reliably.
    native_structured: bool = True
    #: True for small models (~<7B) that cannot reliably emit code inside JSON
    #: strings — the coder then prefers the code-fence path over the JSON contract.
    small_model: bool = False

    def __init__(self, settings: Settings):
        self.settings = settings

    @abstractmethod
    def chat_model(self) -> BaseChatModel:
        """Return a ready-to-invoke chat model (may lazy-load weights)."""

    def available(self) -> tuple[bool, str]:
        """(ok, reason). Default: require an env var named in ``required_env``."""
        env = getattr(self, "required_env", None)
        if env and not os.environ.get(env):
            return False, f"missing {env}"
        return True, "ok"


# ---------------------------------------------------------------------------
# JSON extraction — tolerant of fences, prose preambles and trailing text
# ---------------------------------------------------------------------------
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
_CODE_FENCE_RE = re.compile(r"```[a-zA-Z0-9_+-]*\n(.*?)```", re.DOTALL)


def extract_code_fence(text: str) -> str | None:
    """Return the largest fenced code block, or the whole text if it plainly
    *is* code (no fence but no prose either). Used by the small-model coder
    fallback where JSON-wrapping whole files is unreliable."""
    blocks = _CODE_FENCE_RE.findall(text)
    if blocks:
        return max(blocks, key=len).strip("\n") + "\n"
    stripped = text.strip()
    if not stripped:
        return None
    # Heuristic: an unfenced reply that starts like code, not prose.
    first = stripped.splitlines()[0]
    if first.startswith(("def ", "class ", "import ", "from ", "function ",
                         "const ", "export ", "package ", "using ", "#include",
                         "public ", "fn ", "<?php")):
        return stripped + "\n"
    return None


def extract_json(text: str) -> Any:
    """Pull the first JSON object/array out of model text. Raises ValueError."""
    text = text.strip()
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    # Fast path: the whole thing is JSON.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Scan for the first balanced {...} or [...] region.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        while start != -1:
            depth, in_str, esc = 0, False, False
            for i in range(start, len(text)):
                c = text[i]
                if esc:
                    esc = False
                    continue
                if c == "\\":
                    esc = True
                elif c == '"':
                    in_str = not in_str
                elif not in_str:
                    if c == opener:
                        depth += 1
                    elif c == closer:
                        depth -= 1
                        if depth == 0:
                            try:
                                return json.loads(text[start:i + 1])
                            except json.JSONDecodeError:
                                break
            start = text.find(opener, start + 1)
    raise ValueError("no parseable JSON found in model output")


def _schema_instruction(schema: Type[BaseModel]) -> str:
    js = json.dumps(schema.model_json_schema(), indent=None)
    return (
        f"Respond with ONLY a JSON object valid against this JSON Schema "
        f"(no prose, no markdown fences):\n{js}"
    )


def invoke_structured(
    llm: BaseChatModel,
    messages: Sequence[BaseMessage],
    schema: Type[TModel],
    *,
    native: bool = True,
    max_retries: int = 2,
) -> TModel:
    """Invoke ``llm`` and coerce the reply into ``schema``.

    1. If ``native``, try ``with_structured_output`` (tool-calling / JSON mode
       on cloud providers).
    2. Otherwise (or on native failure) fall back to an explicit JSON contract:
       instruct → parse → validate → on error, feed the validation error back
       and retry, up to ``max_retries`` times.
    """
    if native:
        try:
            out = llm.with_structured_output(schema).invoke(list(messages))
            if isinstance(out, schema):
                return out
            if isinstance(out, dict):
                return schema.model_validate(out)
        except (NotImplementedError, ValidationError):
            pass
        except Exception:
            # Native path can fail on providers without tool support for the
            # chosen model; degrade to the JSON contract rather than dying.
            pass

    convo: list[BaseMessage] = [*messages, HumanMessage(content=_schema_instruction(schema))]
    last_err: Exception | None = None
    for _ in range(max_retries + 1):
        reply = llm.invoke(convo)
        text = reply.content if isinstance(reply.content, str) else str(reply.content)
        try:
            data = extract_json(text)
            return schema.model_validate(data)
        except (ValueError, ValidationError) as e:
            last_err = e
            convo = [*convo, reply, HumanMessage(content=(
                f"Your previous reply was not valid: {e}\n"
                f"Reply again with ONLY the corrected JSON object."
            ))]
    raise StructuredOutputError(
        f"model failed to produce valid {schema.__name__} after {max_retries + 1} attempts: {last_err}"
    )
