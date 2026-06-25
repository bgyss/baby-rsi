"""Goal 07 — token/USD ceilings halt-and-escalate, and the audit ledger records spend."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from siro.archive import ModelCallLedger
from siro.budget import BudgetExceeded, BudgetLimits, BudgetTracker
from siro.providers.base import Usage
from siro.schemas import ModelCall


def test_unbounded_budget_never_raises():
    tracker = BudgetTracker(BudgetLimits())
    tracker.charge(Usage(input_tokens=10_000, output_tokens=10_000, cost_usd=999.0))
    assert tracker.run_usd == 999.0


def test_per_call_token_ceiling_halts():
    tracker = BudgetTracker(BudgetLimits(max_tokens_per_call=100))
    with pytest.raises(BudgetExceeded) as exc:
        tracker.charge(Usage(input_tokens=80, output_tokens=40))
    assert exc.value.kind == "tokens_per_call"


def test_per_run_usd_ceiling_halts():
    tracker = BudgetTracker(BudgetLimits(max_usd_per_run=1.0))
    tracker.charge(Usage(cost_usd=0.6))  # ok
    with pytest.raises(BudgetExceeded) as exc:
        tracker.charge(Usage(cost_usd=0.6))  # cumulative 1.2 > 1.0
    assert exc.value.kind == "usd_per_run"
    assert exc.value.observed == pytest.approx(1.2)


def test_per_day_usd_ceiling_reads_ledger(tmp_path):
    ledger = ModelCallLedger(tmp_path / "model_calls.jsonl")
    # Two prior calls today already near the daily ceiling.
    for _ in range(2):
        ledger.append(ModelCall(provider="anthropic", model="m", prompt_hash="h", cost_usd=20.0))
    tracker = BudgetTracker(BudgetLimits(max_usd_per_day=50.0), ledger=ledger)
    # This call is logged first (as the controller does), then charged.
    ledger.append(ModelCall(provider="anthropic", model="m", prompt_hash="h", cost_usd=20.0))
    with pytest.raises(BudgetExceeded) as exc:
        tracker.charge(Usage(cost_usd=20.0))  # day total now 60 > 50
    assert exc.value.kind == "usd_per_day"


def test_per_day_ignores_other_days(tmp_path):
    ledger = ModelCallLedger(tmp_path / "model_calls.jsonl")
    yesterday = datetime.now(timezone.utc) - timedelta(days=2)
    ledger.append(
        ModelCall(provider="a", model="m", prompt_hash="h", cost_usd=999.0, created_at=yesterday)
    )
    tracker = BudgetTracker(BudgetLimits(max_usd_per_day=50.0), ledger=ledger)
    tracker.charge(Usage(cost_usd=1.0))  # only today's spend counts → no raise
    assert tracker.run_usd == 1.0


def test_limits_from_config_block():
    limits = BudgetLimits.from_config(
        {"max_usd_per_run": 5.0, "max_usd_per_day": 50.0, "max_tokens_per_call": 8000}
    )
    assert not limits.unbounded
    assert limits.max_usd_per_run == 5.0
    assert BudgetLimits.from_config(None).unbounded
