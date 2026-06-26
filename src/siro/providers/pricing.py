"""Cost estimation — turning token counts into the USD figures the budget reads.

Prices are USD per **million** tokens, ``(input, output)``. They are *estimates* for
the audit ledger and budget ceilings, not billing truth: a config ``prices`` block
overrides them per provider (``docs/07_model_providers_and_tiers.md``), and local
models are always free. Keeping the table here (not hardcoded in clients) is what lets
the outer loop reflect on spend without touching provider code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class PriceRecord:
    """A dated, source-attributed USD-per-1M-token rate for one model/provider."""

    input_per_mtok: float
    output_per_mtok: float
    cached_input_per_mtok: float | None = None
    last_reviewed: str = ""
    source: str = "built-in estimate"

    @classmethod
    def from_block(cls, block: dict[str, Any]) -> "PriceRecord":
        return cls(
            input_per_mtok=float(block.get("input_per_mtok", 0.0)),
            output_per_mtok=float(block.get("output_per_mtok", 0.0)),
            cached_input_per_mtok=(
                None
                if block.get("cached_input_per_mtok") is None
                else float(block["cached_input_per_mtok"])
            ),
            last_reviewed=str(block.get("last_reviewed") or ""),
            source=str(block.get("source_url") or block.get("source_note") or ""),
        )


#: Rich default records keyed by exact model name. Defaults are repository estimates and
#: should be superseded by dated config overrides before scale decisions.
DEFAULT_PRICE_RECORDS: dict[str, PriceRecord] = {
    "claude-opus-4-8": PriceRecord(5.0, 25.0, source="built-in anthropic estimate"),
    "claude-sonnet-4-6": PriceRecord(3.0, 15.0, source="built-in anthropic estimate"),
    "claude-haiku-4-5-20251001": PriceRecord(1.0, 5.0, source="built-in anthropic estimate"),
    "gpt-5.4": PriceRecord(2.5, 15.0, source="built-in openai estimate"),
}

#: Backward-compatible USD per 1M-token tuple table, keyed by exact model name.
DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "gpt-5.4": (2.5, 15.0),
}

#: Fallback per-backend prices when a model name is unknown. Local is always free.
BACKEND_DEFAULT_PRICES: dict[str, PriceRecord] = {
    "local": PriceRecord(0.0, 0.0, source="local inference default"),
    "llamacpp": PriceRecord(0.0, 0.0, source="local inference default"),
    "anthropic": PriceRecord(5.0, 25.0, source="built-in anthropic backend estimate"),
    "openai": PriceRecord(2.5, 15.0, source="built-in openai backend estimate"),
}


@dataclass(frozen=True)
class Pricing:
    """A resolved USD-per-1M-token rate plus the metadata explaining its source."""

    input_per_mtok: float = 0.0
    output_per_mtok: float = 0.0
    cached_input_per_mtok: float | None = None
    source: str = "free"
    source_type: str = "default"
    last_reviewed: str = ""
    missing: bool = False

    @classmethod
    def resolve(
        cls,
        backend: str,
        model: str,
        override: "Pricing | PriceRecord | tuple[float, float] | None" = None,
    ) -> "Pricing":
        """Pick a rate: explicit config override > model table > backend default > free."""
        if override is not None:
            return cls._from_override(override)
        if model in DEFAULT_PRICE_RECORDS:
            return cls._from_record(DEFAULT_PRICE_RECORDS[model], source_type="default")
        if backend in BACKEND_DEFAULT_PRICES:
            return cls._from_record(BACKEND_DEFAULT_PRICES[backend], source_type="backend_default")
        return cls(source="missing", source_type="missing", missing=True)

    @classmethod
    def _from_override(cls, override: "Pricing | PriceRecord | tuple[float, float]") -> "Pricing":
        if isinstance(override, Pricing):
            return override
        if isinstance(override, PriceRecord):
            return cls._from_record(override, source_type="override")
        return cls(float(override[0]), float(override[1]), source="config override", source_type="override")

    @classmethod
    def _from_record(cls, record: PriceRecord, *, source_type: str) -> "Pricing":
        return cls(
            input_per_mtok=record.input_per_mtok,
            output_per_mtok=record.output_per_mtok,
            cached_input_per_mtok=record.cached_input_per_mtok,
            source=record.source,
            source_type=source_type,
            last_reviewed=record.last_reviewed,
        )

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.input_per_mtok + output_tokens * self.output_per_mtok
        ) / 1_000_000.0

    def metadata(self) -> dict[str, Any]:
        return {
            "input_per_mtok": self.input_per_mtok,
            "output_per_mtok": self.output_per_mtok,
            "cached_input_per_mtok": self.cached_input_per_mtok,
            "source": self.source,
            "source_type": self.source_type,
            "last_reviewed": self.last_reviewed,
            "missing": self.missing,
        }

    def review_age_days(self, today: date | None = None) -> int | None:
        if not self.last_reviewed:
            return None
        today = today or date.today()
        try:
            reviewed = datetime.strptime(self.last_reviewed, "%Y-%m-%d").date()
        except ValueError:
            return None
        return (today - reviewed).days


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token) for servers that omit a ``usage`` block."""
    return max(1, len(text) // 4)


def parse_price_override(block: dict[str, Any] | None) -> Pricing | None:
    """Parse an optional config ``prices`` block into a resolved override."""
    if not isinstance(block, dict):
        return None
    record = PriceRecord.from_block(block)
    return Pricing._from_record(record, source_type="override")


__all__ = [
    "DEFAULT_PRICES",
    "DEFAULT_PRICE_RECORDS",
    "BACKEND_DEFAULT_PRICES",
    "PriceRecord",
    "Pricing",
    "estimate_tokens",
    "parse_price_override",
]
