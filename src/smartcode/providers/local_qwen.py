"""Local Qwen2.5-1.5B-Instruct provider via transformers.

Wrapped as a LangChain ``BaseChatModel`` so it speaks the same
``.invoke(messages)`` contract as the cloud providers. Weights load lazily on
first call. Pascal-era GPUs (e.g. GTX 1050 Ti) lack bf16, so we prefer fp16 on
CUDA and fp32 on CPU, with a graceful CPU fallback on CUDA OOM.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

from .base import BaseProvider, ProviderError


def _to_chat(messages: List[BaseMessage]) -> list[dict]:
    out = []
    for m in messages:
        role = "user"
        if isinstance(m, SystemMessage):
            role = "system"
        elif isinstance(m, AIMessage):
            role = "assistant"
        content = m.content if isinstance(m.content, str) else str(m.content)
        out.append({"role": role, "content": content})
    return out


class LocalQwenChatModel(BaseChatModel):
    model_path: str
    device: str = "auto"       # auto | cuda | cpu
    dtype: str = "auto"        # auto | fp16 | fp32 | bf16
    temperature: float = 0.2
    max_new_tokens: int = 1024

    _tok: Any = PrivateAttr(default=None)
    _model: Any = PrivateAttr(default=None)
    _resolved_device: str = PrivateAttr(default="cpu")

    @property
    def _llm_type(self) -> str:
        return "local-qwen"

    # -- lazy loading -------------------------------------------------------
    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as e:
            raise ProviderError(
                "local provider needs torch+transformers — install with "
                "`uv sync --extra local` (or the CUDA torch wheel)."
            ) from e

        device = self.device
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        if self.dtype == "auto":
            dtype = torch.float16 if device == "cuda" else torch.float32
        else:
            dtype = {"fp16": torch.float16, "fp32": torch.float32,
                     "bf16": torch.bfloat16}[self.dtype]

        self._tok = AutoTokenizer.from_pretrained(self.model_path)

        def load_on(dev: str, dt: Any) -> Any:
            try:
                model = AutoModelForCausalLM.from_pretrained(self.model_path, dtype=dt)
            except TypeError:  # transformers < 4.56 uses torch_dtype
                model = AutoModelForCausalLM.from_pretrained(self.model_path, torch_dtype=dt)
            return model.to(dev)

        try:
            self._model = load_on(device, dtype)
            self._resolved_device = device
        except Exception:
            if device == "cuda":  # OOM or driver trouble → CPU fallback
                self._model = load_on("cpu", torch.float32)
                self._resolved_device = "cpu"
            else:
                raise
        self._model.eval()

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        self._load()
        import torch

        prompt = self._tok.apply_chat_template(
            _to_chat(messages), tokenize=False, add_generation_prompt=True
        )
        inputs = self._tok(prompt, return_tensors="pt").to(self._resolved_device)
        do_sample = self.temperature > 0
        with torch.no_grad():
            out = self._model.generate(
                **inputs,
                max_new_tokens=self.max_new_tokens,
                do_sample=do_sample,
                temperature=self.temperature if do_sample else None,
                pad_token_id=self._tok.eos_token_id,
            )
        text = self._tok.decode(out[0][inputs["input_ids"].shape[1]:],
                                skip_special_tokens=True)
        if stop:
            for s in stop:
                idx = text.find(s)
                if idx != -1:
                    text = text[:idx]
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])


class LocalQwenProvider(BaseProvider):
    id = "local"
    #: A 1.5B SLM has no reliable tool-calling — use the JSON contract path.
    native_structured = False
    small_model = True

    def chat_model(self) -> BaseChatModel:
        s = self.settings
        return LocalQwenChatModel(
            model_path=str(s.local_model_path),
            device=s.local_device,
            dtype=s.local_dtype,
            temperature=s.local_temperature,
            max_new_tokens=s.local_max_new_tokens,
        )

    def available(self) -> tuple[bool, str]:
        p = Path(self.settings.local_model_path)
        if not p.exists():
            return False, f"model dir not found: {p}"
        try:
            import torch  # noqa: F401
            import transformers  # noqa: F401
        except ImportError:
            return False, "torch/transformers not installed (uv sync --extra local)"
        return True, f"model at {p}"
