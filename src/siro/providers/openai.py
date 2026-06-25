"""OpenAI (GPT) backend — Chat Completions with tool use and structured output.

Shares the OpenAI-compatible plumbing with the local client; the only differences are
``base_url`` (``https://api.openai.com/v1``), a real API key read from the configured
env var **in the control plane only**, and non-zero :class:`Pricing`. Structured output
is enforced with ``response_format=json_schema`` against a Pydantic schema; the parsed,
validated instance is returned on :attr:`ModelResponse.structured`.
"""

from __future__ import annotations

from ._http import Transport
from ._openai_compatible import OpenAICompatibleClient
from .ops import RetryPolicy
from .pricing import Pricing

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-5.4"


class OpenAIClient(OpenAICompatibleClient):
    """GPT via the OpenAI Chat Completions API."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 120.0,
        temperature: float = 0.7,
        pricing: Pricing | None = None,
        retry_policy: RetryPolicy | None = None,
        allowed_endpoints: list[str] | None = None,
        transport: Transport | None = None,
    ) -> None:
        super().__init__(
            provider="openai",
            base_url=base_url,
            model=model,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            temperature=temperature,
            pricing=pricing or Pricing.resolve("openai", model),
            retry_policy=retry_policy,
            allowed_endpoints=allowed_endpoints,
            transport=transport,
        )


__all__ = ["OpenAIClient", "DEFAULT_BASE_URL", "DEFAULT_MODEL"]
