"""Provider name -> implementation.

Imports are lazy so a user with only an Anthropic key never needs httpx to
resolve an OpenAI import, and so tests can exercise the registry without every
optional dependency present.
"""
from __future__ import annotations

from sublease.errors import ProviderError
from sublease.llm.base import LLMProvider

PROVIDER_NAMES = {"anthropic", "openai", "ollama", "claude-cli"}
DEFAULT_PROVIDER = "anthropic"
DEFAULT_MODEL = "claude-haiku-4-5"


def get_provider(name: str, model: str | None = None, **kwargs) -> LLMProvider:
    if name == "anthropic":
        from sublease.llm.anthropic_provider import AnthropicProvider
        return AnthropicProvider(model=model or DEFAULT_MODEL, **kwargs)
    if name == "openai":
        from sublease.llm.openai_provider import OpenAIProvider
        return OpenAIProvider(model=model or "gpt-4o-mini", **kwargs)
    if name == "ollama":
        from sublease.llm.ollama_provider import OllamaProvider
        return OllamaProvider(model=model or "llama3.1", **kwargs)
    if name == "claude-cli":
        from sublease.llm.claude_cli_provider import ClaudeCLIProvider
        return ClaudeCLIProvider(model=model or "haiku", **kwargs)
    raise ProviderError(
        f"unknown provider {name!r}; expected one of {sorted(PROVIDER_NAMES)}")
