"""Budget ceilings — tokens and dollars as a first-class budget (Goal 07).

Frontier APIs introduce spend and a runaway-cost risk, so the controller treats tokens
and USD like compute time (``docs/07_model_providers_and_tiers.md``): per-run and
per-day USD ceilings plus a per-call token ceiling. A breach **halts the run and
escalates** — :class:`BudgetExceeded` is raised, never swallowed, because exceeding a
ceiling is exactly the kind of escalation a human must approve.

Per-day spend is computed from the audit ledger (``runs/model_calls.jsonl``) so it holds
*across* runs in a day, not just within one process — the ledger is the single source of
truth for what was spent. Budgets are a bound the loop may never widen on its own
(``docs/13_self_improvement_loop.md``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .archive import ModelCallLedger
    from .providers.base import Usage


class BudgetExceeded(RuntimeError):
    """Raised when a token/USD ceiling is breached: halt the run and escalate."""

    def __init__(self, message: str, *, kind: str, limit: float, observed: float) -> None:
        super().__init__(message)
        self.kind = kind
        self.limit = limit
        self.observed = observed


@dataclass(frozen=True)
class BudgetLimits:
    """The configured ceilings. ``None`` means unbounded (the Tier 0 default)."""

    max_usd_per_run: float | None = None
    max_usd_per_day: float | None = None
    max_tokens_per_call: int | None = None

    @classmethod
    def from_config(cls, block: dict[str, Any] | None) -> "BudgetLimits":
        block = block or {}
        return cls(
            max_usd_per_run=block.get("max_usd_per_run"),
            max_usd_per_day=block.get("max_usd_per_day"),
            max_tokens_per_call=block.get("max_tokens_per_call"),
        )

    @property
    def unbounded(self) -> bool:
        return (
            self.max_usd_per_run is None
            and self.max_usd_per_day is None
            and self.max_tokens_per_call is None
        )


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class BudgetTracker:
    """Accumulates spend across a run and enforces the ceilings.

    The controller calls :meth:`charge` once per model call, *after* the call is logged
    to the ledger (so every call stays auditable even the one that trips the ceiling).
    A breach raises :class:`BudgetExceeded`, which propagates out of the loop as the
    halt-and-escalate signal.
    """

    def __init__(
        self,
        limits: BudgetLimits | None = None,
        ledger: "ModelCallLedger | None" = None,
    ) -> None:
        self.limits = limits or BudgetLimits()
        self.ledger = ledger
        self.run_usd = 0.0
        self.run_tokens = 0

    def _prior_day_usd(self) -> float:
        """USD already spent *today* per the ledger, before this run started."""
        if self.ledger is None:
            return 0.0
        today = _today_utc()
        total = 0.0
        for call in self.ledger.read_all():
            if call.created_at.astimezone(timezone.utc).strftime("%Y-%m-%d") == today:
                total += call.cost_usd
        return total

    def charge(self, usage: "Usage") -> None:
        """Record one call's usage and raise if any ceiling is now breached."""
        lim = self.limits

        if lim.max_tokens_per_call is not None and usage.total_tokens > lim.max_tokens_per_call:
            raise BudgetExceeded(
                f"per-call tokens {usage.total_tokens} exceed ceiling {lim.max_tokens_per_call}",
                kind="tokens_per_call",
                limit=float(lim.max_tokens_per_call),
                observed=float(usage.total_tokens),
            )

        self.run_usd += usage.cost_usd
        self.run_tokens += usage.total_tokens

        if lim.max_usd_per_run is not None and self.run_usd > lim.max_usd_per_run:
            raise BudgetExceeded(
                f"run spend ${self.run_usd:.4f} exceeds ceiling ${lim.max_usd_per_run:.2f}",
                kind="usd_per_run",
                limit=lim.max_usd_per_run,
                observed=self.run_usd,
            )

        if lim.max_usd_per_day is not None:
            # Prior-ledger spend already includes this call (logged before charge), so
            # read it fresh rather than double-counting self.run_usd.
            day_usd = self._prior_day_usd()
            if day_usd > lim.max_usd_per_day:
                raise BudgetExceeded(
                    f"day spend ${day_usd:.4f} exceeds ceiling ${lim.max_usd_per_day:.2f}",
                    kind="usd_per_day",
                    limit=lim.max_usd_per_day,
                    observed=day_usd,
                )


__all__ = ["BudgetExceeded", "BudgetLimits", "BudgetTracker"]
