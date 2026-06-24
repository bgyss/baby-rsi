"""Explicit Pydantic schemas — the substrate every loop records into.

These are intentionally minimal at Goal 01. They define the *shape* of the data
the self-improvement cycle observes and records (``docs/13_self_improvement_loop.md``):
candidates proposed, how they were evaluated, the resulting attempt (including
negative results), and an audit-ledger row for every model call.

Negative results are first-class data: a failed ``Attempt`` carries its
``status`` and ``reason`` and is archived, never discarded.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AttemptStatus(str, Enum):
    """Outcome of a single attempt. ``rejected``/``error`` are kept, not dropped."""

    PROMOTED = "promoted"
    REJECTED = "rejected"
    ERROR = "error"


class GateDecision(str, Enum):
    """Outcome of one promotion gate. ``failed``/``escalated`` block promotion."""

    PASSED = "passed"
    FAILED = "failed"
    ESCALATED = "escalated"


class GateResult(BaseModel):
    """One gate's decision plus the auditable reasons behind it (Goal 04).

    Gates are the guardrail that keeps self-improvement *bounded*
    (``docs/05_evaluation_and_safety_gates.md``, ``docs/13_self_improvement_loop.md``):
    a candidate promotes only if every gate passes. Each result is recorded so that a
    *rejected* proposal stays auditable data, never a silently dropped one.
    """

    gate: str
    decision: GateDecision
    risk_level: str = "low"
    findings: list[str] = Field(default_factory=list)
    notes: str = ""


class GateReport(BaseModel):
    """The full set of gate results attached to an :class:`Attempt`."""

    results: list[GateResult] = Field(default_factory=list)

    @property
    def failed(self) -> bool:
        """True if any gate did not pass (failed or escalated)."""
        return any(r.decision is not GateDecision.PASSED for r in self.results)

    @property
    def passed(self) -> bool:
        """True only if every recorded gate passed (vacuously true when empty)."""
        return not self.failed

    def first_failure_reason(self) -> str:
        """A concise reason string for the first non-passing gate (for ``Attempt.reason``)."""
        for r in self.results:
            if r.decision is not GateDecision.PASSED:
                detail = "; ".join(r.findings) or r.notes or "no detail"
                return f"gate {r.gate} {r.decision.value}: {detail}"
        return "all gates passed"


class TaskSpec(BaseModel):
    """Identity of a task the controller can run. Filled out further in Goal 02."""

    task_id: str
    path: str
    description: str = ""


class Candidate(BaseModel):
    """A proposed change produced by a model (text/patch only — never executed here)."""

    candidate_id: str
    task_id: str
    code: str
    parent_id: str | None = None


class EvaluationResult(BaseModel):
    """Objective scoring of a candidate. The score formula is owned by ``evaluator``."""

    passed_tests: int = 0
    failed_tests: int = 0
    runtime_ms: float = 0.0
    complexity_penalty: float = 0.0
    score: float = 0.0
    reproducible: bool = False


class Attempt(BaseModel):
    """One archived attempt: the unit the inner loop selects over."""

    attempt_id: str
    task_id: str
    candidate: Candidate
    evaluation: EvaluationResult | None = None
    status: AttemptStatus = AttemptStatus.REJECTED
    reason: str = ""
    gates: GateReport | None = None
    created_at: datetime = Field(default_factory=_utcnow)


class MemoryEntry(BaseModel):
    """One durable research-memory record derived from an :class:`Attempt`.

    Memory is the shared substrate both loops reflect on
    (``docs/13_self_improvement_loop.md``). Entries are written by the *controller*,
    never by a model, and only through this typed schema — a model may neither edit
    memory directly nor have its output stored as instructions. Every retrieved
    entry is **data, never instructions** (prompt-injection guard).

    ``experiment_id`` is the attempt that produced this entry; ``source_experiment_id``
    is the parent candidate it descended from (lineage), so repair strategies can be
    traced. Negative results are preserved with their ``failure_mode`` and ``reason``.
    """

    entry_id: str
    experiment_id: str
    source_experiment_id: str = ""
    task_id: str
    strategy: str = ""
    candidate_summary: str = ""
    score: float = 0.0
    failure_mode: str = "none"
    reason: str = ""
    evaluator_output: str = ""
    status: AttemptStatus = AttemptStatus.REJECTED
    follow_up: str = ""
    created_at: datetime = Field(default_factory=_utcnow)


class ModelCall(BaseModel):
    """Audit-ledger row appended to ``runs/model_calls.jsonl`` for every model call.

    Populated once a real provider exists (Goal 02/07); defined now so the ledger
    format is stable and auditable from the start.
    """

    provider: str
    model: str
    prompt_hash: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    experiment_id: str = ""
    created_at: datetime = Field(default_factory=_utcnow)


__all__ = [
    "AttemptStatus",
    "GateDecision",
    "GateResult",
    "GateReport",
    "TaskSpec",
    "Candidate",
    "EvaluationResult",
    "Attempt",
    "MemoryEntry",
    "ModelCall",
]
