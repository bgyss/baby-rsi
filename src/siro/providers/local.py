"""Local backend — llama.cpp / LlamaBarn over its OpenAI-compatible API (Tier 0).

This is the Goal 02 client refactored into the provider layer. Because the endpoint is
OpenAI-compatible, it shares all request/response plumbing with ``openai.py`` via
:class:`OpenAICompatibleClient`, differing only in ``base_url`` and that **no real
credential is required** — the endpoint is the allow-listed local socket
``127.0.0.1:2276`` (``docs/07_model_providers_and_tiers.md``). Lowering the tier back to
0 selects this client by config alone, with no code change.
"""

from __future__ import annotations

from ._http import Transport
from ._openai_compatible import OpenAICompatibleClient
from .pricing import Pricing

#: Default Tier 0 endpoint — the OpenAI-compatible llama.cpp / LlamaBarn server.
DEFAULT_BASE_URL = "http://127.0.0.1:2276/v1"
DEFAULT_MODEL = "unsloth/Qwen3.6-27B-GGUF:Q8_0"


class LocalOpenAIClient(OpenAICompatibleClient):
    """llama.cpp / LlamaBarn client over OpenAI-compatible ``/chat/completions``.

    Local inference is free, so :class:`Pricing` defaults to zero cost. No API key is
    ever sent. Constructor signature stays backward-compatible with Goal 02 callers.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout_seconds: float = 120.0,
        temperature: float = 0.7,
        *,
        pricing: Pricing | None = None,
        allowed_endpoints: list[str] | None = None,
        transport: Transport | None = None,
    ) -> None:
        super().__init__(
            provider="local",
            base_url=base_url,
            model=model,
            api_key=None,
            timeout_seconds=timeout_seconds,
            temperature=temperature,
            pricing=pricing or Pricing(),  # local inference is free
            allowed_endpoints=allowed_endpoints,
            transport=transport,
        )


__all__ = ["LocalOpenAIClient", "DEFAULT_BASE_URL", "DEFAULT_MODEL"]
