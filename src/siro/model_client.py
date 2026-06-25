"""Backward-compatible model-client surface (Goal 02 → generalized in Goal 07).

The provider abstraction now lives in :mod:`siro.providers` (local + Claude + GPT). This
module stays as the stable import path the rest of the package and tests already use,
re-exporting the provider layer and keeping the two offline helpers — the scripted and
null clients — that let the whole loop run with no model server and no network.

A model produces *text* — proposals/patches — and nothing else. It never executes
commands, holds a network handle in the execution plane, or sees credentials there
(``docs/07_model_providers_and_tiers.md``).
"""

from __future__ import annotations

from .providers import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    AnthropicClient,
    BaseModelClient,
    LocalOpenAIClient,
    Message,
    ModelClient,
    ModelRequest,
    ModelResponse,
    OpenAIClient,
    ProviderConfig,
    ToolSpec,
    Usage,
    build_client,
    extract_code,
)
from .providers.base import ToolCall


class NullModelClient(BaseModelClient):
    """Offline placeholder that refuses to generate. Useful as an explicit default."""

    provider = "null"
    model = "null"

    def _complete(self, request: ModelRequest) -> ModelResponse:  # noqa: ARG002 - stub
        raise NotImplementedError(
            "No model provider is configured. Use LocalOpenAIClient (llama.cpp / "
            "LlamaBarn), a frontier client, or a ScriptedModelClient for offline tests."
        )


class ScriptedModelClient(BaseModelClient):
    """Deterministic offline client that replays canned responses, in order.

    Lets the full code-improver loop and the frontier organization (and their tests) run
    for N generations with no model server and no network — the same way negative results
    stay reproducible. Usage is zero-cost so it never trips a budget ceiling.

    ``provider``/``model`` are configurable so an offline test can simulate *distinct*
    providers (e.g. an Implementation client vs a different-provider Safety reviewer) and
    exercise the cross-model-review invariant fully offline.
    """

    def __init__(
        self,
        responses: list[str],
        *,
        provider: str = "scripted",
        model: str = "scripted",
    ) -> None:
        super().__init__()
        if not responses:
            raise ValueError("ScriptedModelClient needs at least one response")
        self.provider = provider
        self.model = model
        self._responses = list(responses)
        self._i = 0

    def _complete(self, request: ModelRequest) -> ModelResponse:  # noqa: ARG002 - by design
        text = self._responses[min(self._i, len(self._responses) - 1)]
        self._i += 1
        return ModelResponse(text=text, provider=self.provider, model=self.model, usage=Usage())


__all__ = [
    "ModelClient",
    "BaseModelClient",
    "ModelRequest",
    "ModelResponse",
    "Message",
    "ToolSpec",
    "ToolCall",
    "Usage",
    "NullModelClient",
    "ScriptedModelClient",
    "LocalOpenAIClient",
    "AnthropicClient",
    "OpenAIClient",
    "ProviderConfig",
    "build_client",
    "extract_code",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
]
