"""Thin cloud provider wrappers over the installed langchain-* integrations.

Imports are deferred to :meth:`chat_model` so a missing optional integration
only breaks the provider that needs it, and ``available()`` can report health
without importing anything heavy.
"""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel

from .base import BaseProvider, ProviderError

_TEMPERATURE = 0.2  # code generation favours low-variance output


class GroqProvider(BaseProvider):
    id = "groq"
    required_env = "GROQ_API_KEY"

    def chat_model(self) -> BaseChatModel:
        try:
            from langchain_groq import ChatGroq
        except ImportError as e:
            raise ProviderError("langchain-groq is not installed") from e
        return ChatGroq(model=self.settings.groq_model, temperature=_TEMPERATURE)


class AnthropicProvider(BaseProvider):
    id = "anthropic"
    required_env = "ANTHROPIC_API_KEY"

    def chat_model(self) -> BaseChatModel:
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as e:
            raise ProviderError("langchain-anthropic is not installed") from e
        return ChatAnthropic(model=self.settings.anthropic_model,
                             temperature=_TEMPERATURE, max_tokens=4096)


class OpenAIProvider(BaseProvider):
    id = "openai"
    required_env = "OPENAI_API_KEY"

    def chat_model(self) -> BaseChatModel:
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as e:
            raise ProviderError("langchain-openai is not installed") from e
        return ChatOpenAI(model=self.settings.openai_model, temperature=_TEMPERATURE)


class GoogleProvider(BaseProvider):
    id = "google"
    required_env = "GOOGLE_API_KEY"

    def chat_model(self) -> BaseChatModel:
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError as e:
            raise ProviderError("langchain-google-genai is not installed") from e
        return ChatGoogleGenerativeAI(model=self.settings.google_model,
                                      temperature=_TEMPERATURE)
