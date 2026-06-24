"""Model client abstraction (Protocol).

Goal 01 defines the smallest possible interface so the Goal 02 code-improver loop
can depend on it, and Goal 07 can generalize it into the full provider layer
(local llama.cpp/LlamaBarn + Claude + GPT) without breaking callers.

A model produces *text* — proposals/patches — and nothing else. It never executes
commands, holds a network handle in the execution plane, or sees credentials there
(``docs/07_model_providers_and_tiers.md``).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ModelClient(Protocol):
    """Minimal provider-neutral interface. Generalized in Goal 07."""

    def generate(self, prompt: str) -> str:
        """Return model output text for ``prompt``."""
        ...


class NullModelClient:
    """Offline placeholder. No provider is wired at Goal 01.

    Exists so the package imports and the loop can be constructed in tests without
    a server. Goal 02 adds a real llama.cpp/LlamaBarn client.
    """

    def generate(self, prompt: str) -> str:  # noqa: ARG002 - stub
        raise NotImplementedError(
            "No model provider is configured. A local llama.cpp/LlamaBarn client "
            "is added in Goal 02."
        )


__all__ = ["ModelClient", "NullModelClient"]
