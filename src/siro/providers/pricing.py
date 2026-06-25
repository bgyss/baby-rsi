"""Cost estimation — turning token counts into the USD figures the budget reads.

Prices are USD per **million** tokens, ``(input, output)``. They are *estimates* for
the audit ledger and budget ceilings, not billing truth: a config ``prices`` block
overrides them per provider (``docs/07_model_providers_and_tiers.md``), and local
models are always free. Keeping the table here (not hardcoded in clients) is what lets
the outer loop reflect on spend without touching provider code.
"""

from __future__ import annotations

from dataclasses import dataclass

#: USD per 1M tokens, ``(input, output)``, keyed by exact model name.
DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (15.0, 75.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "gpt-5.4": (10.0, 30.0),
}

#: Fallback per-backend prices when a model name is unknown. Local is always free.
BACKEND_DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    "local": (0.0, 0.0),
    "llamacpp": (0.0, 0.0),
    "anthropic": (15.0, 75.0),
    "openai": (10.0, 30.0),
}


@dataclass(frozen=True)
class Pricing:
    """A resolved ``(input, output)`` USD-per-1M-token rate for one model."""

    input_per_mtok: float = 0.0
    output_per_mtok: float = 0.0

    @classmethod
    def resolve(
        cls,
        backend: str,
        model: str,
        override: tuple[float, float] | None = None,
    ) -> "Pricing":
        """Pick a rate: explicit config override > model table > backend default > free."""
        if override is not None:
            return cls(override[0], override[1])
        if model in DEFAULT_PRICES:
            return cls(*DEFAULT_PRICES[model])
        if backend in BACKEND_DEFAULT_PRICES:
            return cls(*BACKEND_DEFAULT_PRICES[backend])
        return cls()

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.input_per_mtok + output_tokens * self.output_per_mtok
        ) / 1_000_000.0


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token) for servers that omit a ``usage`` block."""
    return max(1, len(text) // 4)


__all__ = ["DEFAULT_PRICES", "BACKEND_DEFAULT_PRICES", "Pricing", "estimate_tokens"]
