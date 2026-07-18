"""Provider registry: id → provider instance, plus a health report for the CLI."""
from __future__ import annotations

from typing import Type

from ..config import Settings
from .base import BaseProvider, ProviderError
from .cloud import AnthropicProvider, GoogleProvider, GroqProvider, OpenAIProvider
from .local_qwen import LocalQwenProvider
from .mock import MockProvider

_REGISTRY: dict[str, Type[BaseProvider]] = {
    "local": LocalQwenProvider,
    "groq": GroqProvider,
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "google": GoogleProvider,
    "mock": MockProvider,
}


def get_provider(provider_id: str, settings: Settings) -> BaseProvider:
    """Return the provider or raise :class:`ProviderError` with the reason."""
    cls = _REGISTRY.get(provider_id.lower())
    if cls is None:
        raise ProviderError(
            f"unknown provider {provider_id!r}; choose from {sorted(_REGISTRY)}"
        )
    provider = cls(settings)
    ok, reason = provider.available()
    if not ok:
        raise ProviderError(f"provider {provider_id!r} unavailable: {reason}")
    return provider


def available_providers(settings: Settings) -> dict[str, tuple[bool, str]]:
    """Health map for ``smartcode providers`` / ``doctor``."""
    return {pid: cls(settings).available() for pid, cls in _REGISTRY.items()}
