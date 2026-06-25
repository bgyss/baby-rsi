"""Provider abstraction package (Goal 07).

One interface (:class:`ModelClient`) behind every agent, with three backends — local
(llama.cpp / LlamaBarn), Anthropic (Claude), OpenAI (GPT) — selected by **config, not
code**. :func:`build_client` maps a provider config block to a concrete client so the
controller, evaluator, sandbox, gates, and memory never name a provider
(``docs/07_model_providers_and_tiers.md``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from ._http import Transport
from .anthropic import AnthropicClient
from .base import (
    BaseModelClient,
    Message,
    ModelClient,
    ModelRequest,
    ModelResponse,
    ToolCall,
    ToolSpec,
    Usage,
    extract_code,
    messages_hash,
    prompt_hash,
)
from .local import DEFAULT_BASE_URL, DEFAULT_MODEL, LocalOpenAIClient
from .openai import OpenAIClient
from .pricing import Pricing, parse_price_override


@dataclass(frozen=True)
class ProviderConfig:
    """One entry of the config ``providers`` block — pure data, never code.

    ``api_key_env`` names the environment variable holding the credential; the key is
    read only here, in the control plane, and only when the client is built.
    """

    key: str  # the provider's name in the config map ("local", "anthropic", ...)
    backend: str
    name: str  # the model name
    base_url: str | None = None
    api_key_env: str | None = None
    timeout_seconds: float = 120.0
    temperature: float = 0.7
    prices: Pricing | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_block(cls, key: str, block: dict[str, Any]) -> "ProviderConfig":
        return cls(
            key=key,
            backend=str(block.get("backend", key)),
            name=str(block.get("name", "")),
            base_url=block.get("base_url"),
            api_key_env=block.get("api_key_env"),
            timeout_seconds=float(block.get("timeout_seconds", 120.0)),
            temperature=float(block.get("temperature", 0.7)),
            prices=parse_price_override(block.get("prices")),
        )


def _resolve_api_key(env_name: str | None) -> str | None:
    """Read a credential from the control-plane environment (never the execution plane)."""
    if not env_name:
        return None
    return os.environ.get(env_name)


def build_client(
    cfg: ProviderConfig,
    *,
    allowed_endpoints: list[str] | None = None,
    transport: Transport | None = None,
) -> ModelClient:
    """Construct the concrete client for a provider config block.

    Adding a backend means adding a branch here — never editing the controller, gates,
    evaluator, sandbox, or memory schema (the Goal 07 swap-without-editing guarantee).
    """
    backend = cfg.backend.lower()
    pricing = Pricing.resolve(backend, cfg.name, cfg.prices)

    if backend in {"local", "llamacpp"}:
        return LocalOpenAIClient(
            base_url=cfg.base_url or DEFAULT_BASE_URL,
            model=cfg.name or DEFAULT_MODEL,
            timeout_seconds=cfg.timeout_seconds,
            temperature=cfg.temperature,
            pricing=pricing,
            allowed_endpoints=allowed_endpoints,
            transport=transport,
        )
    if backend == "anthropic":
        return AnthropicClient(
            model=cfg.name,
            api_key=_resolve_api_key(cfg.api_key_env),
            base_url=cfg.base_url or "https://api.anthropic.com/v1",
            timeout_seconds=cfg.timeout_seconds,
            temperature=cfg.temperature,
            pricing=pricing,
            allowed_endpoints=allowed_endpoints,
            transport=transport,
        )
    if backend == "openai":
        return OpenAIClient(
            model=cfg.name,
            api_key=_resolve_api_key(cfg.api_key_env),
            base_url=cfg.base_url or "https://api.openai.com/v1",
            timeout_seconds=cfg.timeout_seconds,
            temperature=cfg.temperature,
            pricing=pricing,
            allowed_endpoints=allowed_endpoints,
            transport=transport,
        )
    raise ValueError(f"Unknown provider backend: {cfg.backend!r}")


__all__ = [
    "ProviderConfig",
    "build_client",
    "BaseModelClient",
    "ModelClient",
    "ModelRequest",
    "ModelResponse",
    "Message",
    "ToolSpec",
    "ToolCall",
    "Usage",
    "Pricing",
    "LocalOpenAIClient",
    "AnthropicClient",
    "OpenAIClient",
    "extract_code",
    "prompt_hash",
    "messages_hash",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
]
