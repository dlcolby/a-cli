"""Provider registry — adding a new provider means writing one file implementing
Provider and adding a line here. No other module needs to change."""

from __future__ import annotations

from typing import Optional

from .anthropic_provider import AnthropicProvider
from .base import Provider
from .openai_provider import OpenAIProvider

PROVIDERS = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
}


def create_provider(name: str, api_key: str, base_url: Optional[str] = None) -> Provider:
    try:
        cls = PROVIDERS[name]
    except KeyError:
        raise ValueError(f"Unknown provider '{name}'. Available: {', '.join(PROVIDERS)}")
    return cls(api_key, base_url)


def parse_model_ref(ref: str, default_provider: str) -> tuple[str, str]:
    """Parse 'provider:model' or bare 'model' (uses default_provider)."""
    if ":" in ref:
        provider, model = ref.split(":", 1)
        return provider, model
    return default_provider, ref
