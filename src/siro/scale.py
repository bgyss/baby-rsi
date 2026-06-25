"""Governed compute scale-up — compute budget tiers, allocation, checkpointing (Goal 11).

Tier 2 allows *larger compute and longer experiments* (``docs/07_model_providers_and_tiers.md``),
but a bigger budget is **earned and governed**, never a code change:

- **Compute budget tiers** (``docs/02_research_operating_model.md``): each tier is a hard
  ceiling on wall-clock and memory. The default tier is free; any larger tier requires a
  human-approved governance request (Goal 10) *and* a recorded pass at the next-smaller tier
  — "no direct jump from speculative hypothesis to expensive run" (``docs/00_principles.md``).
- **Hard ceilings on the offline execution plane**: the wall-clock deadline and memory ceiling
  are enforced by :meth:`~siro.sandbox.Sandbox.run_guarded`; a breach halts and escalates
  (:class:`~siro.budget.BudgetExceeded`) and the breach is recorded, leaving the archive
  consistent. Larger compute never opens the network or relaxes plane isolation.
- **Checkpointing + resumability**: a long run records a checkpoint after each completed step,
  written atomically, so a halt-and-escalate loses no work and a rerun can resume.

Lowering the tier removes the capability with no code change: the governed actions simply are
not offered below Tier 2, and with no approvals on record everything default-denies.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .budget import BudgetExceeded
from .governance import GovernanceGate
from .research import ResearchArchive, ResearchTask, hidden_payload, make_candidate
from .schemas import (
    AttemptStatus,
    GovernedAction,
    MetricRecord,
    ResearchAttempt,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .config import SiroConfig
    from .sandbox import GuardedRun, Sandbox

DEFAULT_CHECKPOINT_DIR = Path("runs/checkpoints")

#: The free, default compute tier. Anything above it is governed.
DEFAULT_COMPUTE_TIER = 0


@dataclass(frozen=True)
class ComputeBudget:
    """One compute tier: a hard wall-clock + memory ceiling for an experiment."""

    tier: int
    wall_clock_seconds: float
    memory_mb: int


#: The built-in compute tiers (a config ``compute.tiers`` block overrides these). Each step
#: up roughly widens the ceiling; the default tier (0) is free, higher tiers are governed.
DEFAULT_COMPUTE_TIERS: dict[int, ComputeBudget] = {
    0: ComputeBudget(0, 15.0, 512),
    1: ComputeBudget(1, 60.0, 1024),
    2: ComputeBudget(2, 300.0, 2048),
}


def compute_tiers_from_config(config: "SiroConfig") -> dict[int, ComputeBudget]:
    """Parse a ``compute.tiers`` block from a tier config, or fall back to the defaults."""
    block = (config.raw.get("compute") or {}) if getattr(config, "raw", None) else {}
    tiers = block.get("tiers")
    if not tiers:
        return dict(DEFAULT_COMPUTE_TIERS)
    parsed: dict[int, ComputeBudget] = {}
    for key, spec in tiers.items():
        t = int(key)
        parsed[t] = ComputeBudget(
            tier=t,
            wall_clock_seconds=float(spec["wall_clock_seconds"]),
            memory_mb=int(spec["memory_mb"]),
        )
    return parsed


class ComputeAllocationError(RuntimeError):
    """Raised when a compute tier is requested without first passing the smaller tier."""


def _short_id() -> str:
    return uuid.uuid4().hex[:12]


class CheckpointStore:
    """Atomic, per-experiment JSON checkpoints under ``runs/checkpoints/`` (Goal 11).

    A checkpoint is the resumable state of a long experiment (its best result so far and the
    highest compute tier it has passed). Writes are atomic (temp file + ``os.replace``) so a
    halt mid-write never corrupts a checkpoint.
    """

    def __init__(self, directory: str | Path = DEFAULT_CHECKPOINT_DIR) -> None:
        self.directory = Path(directory)

    def _path(self, experiment_id: str) -> Path:
        return self.directory / f"{experiment_id}.json"

    def save(self, experiment_id: str, state: dict) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(experiment_id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        os.replace(tmp, path)  # atomic on POSIX

    def load(self, experiment_id: str) -> dict | None:
        path = self._path(experiment_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))


class ComputeAllocator:
    """Grants a compute budget for a tier, gated by governance + promotion-before-budget."""

    def __init__(
        self,
        gate: GovernanceGate,
        *,
        tiers: dict[int, ComputeBudget] | None = None,
        default_tier: int = DEFAULT_COMPUTE_TIER,
        checkpoints: CheckpointStore | None = None,
    ) -> None:
        self.gate = gate
        self.tiers = tiers or dict(DEFAULT_COMPUTE_TIERS)
        self.default_tier = default_tier
        self.checkpoints = checkpoints or CheckpointStore()

    def budget_for(self, tier: int) -> ComputeBudget:
        if tier not in self.tiers:
            raise KeyError(f"unknown compute tier {tier!r}; known: {sorted(self.tiers)}")
        return self.tiers[tier]

    def highest_passed_tier(self, experiment_id: str) -> int | None:
        state = self.checkpoints.load(experiment_id)
        if state is None:
            return None
        value = state.get("highest_passed_tier")
        return int(value) if value is not None else None

    def record_pass(self, experiment_id: str, tier: int) -> None:
        """Record that ``experiment_id`` passed its gates at ``tier`` (lineage for the next)."""
        state = self.checkpoints.load(experiment_id) or {}
        prior = state.get("highest_passed_tier")
        state["highest_passed_tier"] = max(int(prior), tier) if prior is not None else tier
        self.checkpoints.save(experiment_id, state)

    def allocate(
        self, experiment_id: str, tier: int, *, actor: str = "", rationale: str = ""
    ) -> ComputeBudget:
        """Grant the budget for ``tier`` or refuse (default-deny + promotion-before-budget).

        The default tier is free. A larger tier requires both a recorded pass at the
        next-smaller tier (lineage) **and** a human-approved governance request bound to this
        exact ``(experiment, tier)`` — otherwise it raises :class:`ComputeAllocationError`
        or :class:`~siro.governance.GovernanceDenied`, which the caller surfaces as an
        escalation rather than silently scaling up.
        """
        budget = self.budget_for(tier)
        if tier <= self.default_tier:
            return budget
        passed = self.highest_passed_tier(experiment_id)
        if passed is None or passed < tier - 1:
            raise ComputeAllocationError(
                f"compute tier {tier} for {experiment_id!r} requires first passing tier "
                f"{tier - 1} (highest passed: {passed}). No jump straight to a large budget."
            )
        # Governance approval, bound to the exact (experiment, tier) change.
        self.gate.require(
            GovernedAction.BUDGET_INCREASE,
            target=f"compute_tier:{experiment_id}",
            payload={"compute_tier": tier},
            actor=actor,
            rationale=rationale or f"scale {experiment_id} to compute tier {tier}",
        )
        return budget


@dataclass
class ScaledResult:
    """Outcome of one governed, scaled evaluation."""

    experiment_id: str
    compute_tier: int
    budget: ComputeBudget
    metric: MetricRecord
    attempt: ResearchAttempt
    peak_memory_mb: float


def _metric_from_guarded(task: ResearchTask, run: "GuardedRun") -> MetricRecord:
    """Build the typed metric from a guarded run (mirrors ``research.run_research_eval``)."""
    if not run.ran:
        return MetricRecord(
            primary_name=task.primary_name,
            higher_is_better=task.higher_is_better,
            passed=False,
            reproducible=False,
            error=run.error or "eval.py produced no metric record",
        )
    m = run.metrics
    secondary = {k: float(v) for k, v in (m.get("secondary") or {}).items()}
    return MetricRecord(
        primary_name=task.primary_name,
        primary=float(m["primary"]),
        higher_is_better=task.higher_is_better,
        passed=bool(m.get("passed", False)),
        secondary=secondary,
        reproducible=True,
        notes=str(m.get("notes", "")),
    )


class ScaledRunner:
    """Runs a research evaluation under a governed compute budget, with checkpointing."""

    def __init__(
        self,
        gate: GovernanceGate,
        *,
        sandbox: "Sandbox | None" = None,
        tiers: dict[int, ComputeBudget] | None = None,
        archive: ResearchArchive | None = None,
        checkpoints: CheckpointStore | None = None,
    ) -> None:
        from .sandbox import Sandbox

        self.sandbox = Sandbox() if sandbox is None else sandbox
        self.checkpoints = checkpoints or CheckpointStore()
        self.allocator = ComputeAllocator(gate, tiers=tiers, checkpoints=self.checkpoints)
        self.archive = ResearchArchive() if archive is None else archive

    def run(
        self,
        task: ResearchTask,
        candidate_code: str,
        *,
        compute_tier: int,
        experiment_id: str | None = None,
        actor: str = "",
        rationale: str = "",
    ) -> ScaledResult:
        """Allocate a governed compute budget, run the eval under its ceilings, checkpoint.

        Raises :class:`~siro.governance.GovernanceDenied` or :class:`ComputeAllocationError`
        if the tier isn't authorized, and :class:`~siro.budget.BudgetExceeded` if a ceiling is
        breached at run time — both halt-and-escalate. A breach is still recorded as a
        (negative) attempt and the prior checkpoint is preserved, so the archive stays
        consistent and the experiment can be resumed.
        """
        experiment_id = experiment_id or task.task_id
        budget = self.allocator.allocate(
            experiment_id, compute_tier, actor=actor, rationale=rationale
        )

        files = {task.edit_surface: candidate_code, **task.support_files}
        run = self.sandbox.run_guarded(
            task.eval_path,
            files,
            wall_clock_seconds=budget.wall_clock_seconds,
            memory_mb=budget.memory_mb,
            hidden_payload=hidden_payload(task),
        )

        if run.timed_out or run.memory_exceeded:
            kind = "wall_clock" if run.timed_out else "memory_mb"
            limit = budget.wall_clock_seconds if run.timed_out else float(budget.memory_mb)
            observed = run.runtime_ms / 1000.0 if run.timed_out else run.peak_memory_mb
            self._record_breach(task, experiment_id, compute_tier, run, kind)
            raise BudgetExceeded(run.error, kind=kind, limit=limit, observed=observed)

        metric = _metric_from_guarded(task, run)
        candidate = make_candidate(task, candidate_code)
        status = AttemptStatus.PROMOTED if metric.passed else AttemptStatus.REJECTED
        attempt = ResearchAttempt(
            attempt_id=_short_id(),
            task_id=task.task_id,
            family=task.family,
            candidate=candidate,
            metric=metric,
            status=status,
            reason=(
                f"compute tier {compute_tier}: {metric.primary_name}={metric.primary:g} "
                f"passed={metric.passed} peak_mem={run.peak_memory_mb:.0f}MB"
            ),
        )
        self.archive.append(attempt)
        if metric.passed:
            self.allocator.record_pass(experiment_id, compute_tier)
        self._checkpoint(experiment_id, compute_tier, metric, run)
        return ScaledResult(
            experiment_id=experiment_id,
            compute_tier=compute_tier,
            budget=budget,
            metric=metric,
            attempt=attempt,
            peak_memory_mb=run.peak_memory_mb,
        )

    # --- checkpoints --------------------------------------------------------
    def _checkpoint(
        self, experiment_id: str, tier: int, metric: MetricRecord, run: "GuardedRun"
    ) -> None:
        state = self.checkpoints.load(experiment_id) or {}
        state.update(
            {
                "experiment_id": experiment_id,
                "last_tier": tier,
                "last_primary": metric.primary,
                "last_passed": metric.passed,
                "peak_memory_mb": run.peak_memory_mb,
            }
        )
        if metric.passed:
            prior = state.get("highest_passed_tier")
            state["highest_passed_tier"] = max(int(prior), tier) if prior is not None else tier
        self.checkpoints.save(experiment_id, state)

    def _record_breach(
        self, task: ResearchTask, experiment_id: str, tier: int, run: "GuardedRun", kind: str
    ) -> None:
        """Record a ceiling breach as a negative attempt — first-class, archive stays consistent."""
        attempt = ResearchAttempt(
            attempt_id=_short_id(),
            task_id=task.task_id,
            family=task.family,
            candidate=make_candidate(task, ""),
            metric=None,
            status=AttemptStatus.ERROR,
            reason=f"compute tier {tier} {kind} ceiling breached: {run.error}",
        )
        self.archive.append(attempt)


__all__ = [
    "DEFAULT_CHECKPOINT_DIR",
    "DEFAULT_COMPUTE_TIER",
    "ComputeBudget",
    "DEFAULT_COMPUTE_TIERS",
    "compute_tiers_from_config",
    "ComputeAllocationError",
    "CheckpointStore",
    "ComputeAllocator",
    "ScaledResult",
    "ScaledRunner",
]
