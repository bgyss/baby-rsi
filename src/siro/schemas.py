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


class ProcessConfig(BaseModel):
    """Tunable parameters of the inner-loop *process* — the outer loop's edit surface.

    The meta-research loop (Goal 05, ``docs/13_self_improvement_loop.md``) improves the
    *process*, not individual candidates. This schema is that process's bounded edit
    surface: only the fields here are tunable, so a meta-change is structurally
    incapable of touching safety gates, the evaluator, budgets, permissions, or the
    egress allowlist — those are simply not representable. The "Forbidden meta-changes"
    list in ``goal_05`` is enforced by what this schema *omits*.

    - ``prompt_name`` — which candidate-generation prompt template the controller loads
      (a *prompt revision* is a swap to a revised template file).
    - ``retrieval_limit`` — how many prior lessons memory surfaces to the proposer (a
      *memory retrieval strategy* change).
    """

    prompt_name: str = "code_improver"
    retrieval_limit: int = 5


class MetaChangeKind(str, Enum):
    """Taxonomy of *allowed* meta-changes (``goal_05`` "Allowed meta-changes").

    Forbidden meta-changes (safety/evaluator/permission/budget/network/install) have no
    member here and are unrepresentable in :class:`ProcessConfig` — that omission is the
    bound. At Tier 0 the proposer emits the two kinds that map to a ``ProcessConfig``
    delta; the rest name the taxonomy for later tiers.
    """

    PROMPT_REVISION = "prompt_revision"
    RETRIEVAL_STRATEGY = "retrieval_strategy"
    SCORING_HEURISTIC = "scoring_heuristic"
    SELECTION_HEURISTIC = "selection_heuristic"
    FAILURE_CLUSTERING = "failure_clustering"


class MetaRecommendation(str, Enum):
    """Outcome of A/B validation: promote the process change, or reject it."""

    PROMOTE = "promote"
    REJECT = "reject"


class MetaMetrics(BaseModel):
    """Aggregate process metrics over a benchmark run (``goal_05`` "Metrics").

    These are the *process*-level quantities the outer loop compares old vs new on —
    distinct from a single candidate's :class:`EvaluationResult`.
    """

    n_runs: int = 0
    n_attempts: int = 0
    pass_rate: float = 0.0
    median_generations_to_success: float = 0.0
    invalid_candidates: int = 0
    safety_gate_failures: int = 0
    score_improvement_per_generation: float = 0.0
    strategy_diversity: float = 0.0


class MetaChange(BaseModel):
    """A proposed change to the research *process* (never to a single candidate).

    Carries both the baseline and candidate :class:`ProcessConfig` (so the change is a
    fully-specified, reversible delta), a rollback plan, and a bounds verdict. A
    proposal whose ``bounds_ok`` is false names a forbidden surface and may be recorded
    but never validated or applied.
    """

    meta_change_id: str
    kind: MetaChangeKind
    target: str
    description: str
    rationale: str
    baseline_config: ProcessConfig
    candidate_config: ProcessConfig
    rollback_plan: str
    bounds_ok: bool = True
    forbidden_reason: str = ""


class ABResult(BaseModel):
    """The A/B comparison of the current process vs a proposed one on a fixed benchmark.

    Both arms run the *same* benchmark task set for the *same* number of generations, so
    ``improved`` reflects the process change rather than the inputs.
    """

    baseline: MetaMetrics
    candidate: MetaMetrics
    benchmark_tasks: list[str] = Field(default_factory=list)
    generations: int = 0
    improved: bool = False
    deltas: dict[str, float] = Field(default_factory=dict)
    notes: str = ""


class MetaChangeRecord(BaseModel):
    """A meta-change attempt, stored **separately** from candidate :class:`Attempt`s.

    This separate archive (``runs/meta_changes.jsonl``) is the outer loop's equivalent
    of the inner loop's attempt archive: every proposal — promoted or rejected — is kept
    with its A/B result and rollback plan. ``approved`` is the human-approval flag that
    must be set before a durable process change is applied; the loop may set
    ``recommendation`` but never ``approved``.
    """

    record_id: str
    proposal: MetaChange
    ab_result: ABResult | None = None
    recommendation: MetaRecommendation = MetaRecommendation.REJECT
    approved: bool = False
    applied: bool = False
    reason: str = ""
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
    "ProcessConfig",
    "MetaChangeKind",
    "MetaRecommendation",
    "MetaMetrics",
    "MetaChange",
    "ABResult",
    "MetaChangeRecord",
]
