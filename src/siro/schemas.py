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
from typing import Literal
from uuid import uuid4

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


class TrainConfig(BaseModel):
    """The bounded edit surface of a *training* candidate (Goal 06).

    Like :class:`ProcessConfig` for the meta-loop, this schema *is* the bound: it lists
    exactly the hyperparameters a candidate may tune, and nothing else. The Goal 06
    forbidden changes — validation data, the metric definition, disabling evaluation,
    expanding the runtime budget, downloading datasets, installing packages — are simply
    **unrepresentable** here, so a training candidate is structurally incapable of making
    them. The fixed data/metric/budget live in ``training_task`` and the controller, not
    in this config.

    Range bounds are enforced separately by :func:`siro.training.config_bounds` (the
    training analogue of the safety gate); this schema fixes only the *shape*.
    """

    learning_rate: float = 0.02
    lr_schedule: Literal["constant", "step", "cosine"] = "constant"
    batch_size: int = 32
    hidden_size: int = 8
    momentum: float = 0.0
    weight_decay: float = 0.0
    epochs: int = 40
    init_seed: int = 0


#: A large *finite* sentinel for "worse than any real validation loss". JSON has no
#: ``inf``, so failed/unevaluated runs use this so they still round-trip and can never be
#: selected as best.
WORST_VAL_LOSS = 1e30


class TrainResult(BaseModel):
    """Objective outcome of one training run on the fixed benchmark (Goal 06).

    ``val_loss`` (mean validation cross-entropy, lower is better) is the primary metric;
    ``throughput`` is the secondary metric. ``reproducible`` mirrors the code loop: a run
    that timed out or errored is not a reproducible signal of quality and can never be
    promoted. Failed/unevaluated runs default the losses to :data:`WORST_VAL_LOSS`.
    """

    val_loss: float = WORST_VAL_LOSS
    train_loss: float = WORST_VAL_LOSS
    throughput: float = 0.0
    steps: int = 0
    epochs_completed: int = 0
    wall_clock_ms: float = 0.0
    budget_hit: bool = False
    timed_out: bool = False
    reproducible: bool = False
    error: str = ""


class TrainingAttempt(BaseModel):
    """One archived training attempt — the unit the training inner loop selects over.

    Mirrors :class:`Attempt` but carries a :class:`TrainConfig` (a config delta, logged
    as auditable data) and a :class:`TrainResult` instead of code + test scoring. Stored
    in its own archive (``runs/training_attempts.jsonl``), kept apart from code attempts.
    Negative results — out-of-bounds configs, timeouts, regressions — are recorded with
    their ``status`` and ``reason``, never discarded.
    """

    attempt_id: str
    task_id: str
    config: TrainConfig
    parent_id: str | None = None
    result: TrainResult | None = None
    status: AttemptStatus = AttemptStatus.REJECTED
    reason: str = ""
    gates: GateReport | None = None
    created_at: datetime = Field(default_factory=_utcnow)


class MetricRecord(BaseModel):
    """The typed metric a research task's ``eval.py`` returns (Goal 09).

    Research-shaped tasks (``docs/goal_prompts/goal_09_research_task_suite.md``) score a
    candidate on a continuous **primary** metric plus named **secondary** metrics, instead
    of pytest pass/fail counts. The evaluator (``eval.py``) is the *authority for promotion*:
    it runs in the offline execution plane and emits this record; the controller — never a
    model — decides promotion from it.

    - ``primary`` is the gating metric; ``higher_is_better`` fixes its direction (e.g.
      accuracy is higher-better, validation loss / executed-line count are lower-better).
    - ``passed`` is the correctness/success precondition (all hidden cases satisfied, a
      finite metric produced). A candidate that is not ``passed`` can never be promoted,
      regardless of its primary value.
    - ``reproducible`` mirrors the code/training loops: a timeout or error is not a
      reproducible signal of quality and can never be promoted.
    - ``secondary`` carries informational metrics (runtime, throughput, …) recorded for
      audit and reflection.
    """

    primary_name: str = "primary"
    primary: float = 0.0
    higher_is_better: bool = True
    passed: bool = False
    secondary: dict[str, float] = Field(default_factory=dict)
    reproducible: bool = False
    error: str = ""
    notes: str = ""

    def directional(self) -> float:
        """The primary value oriented so that *larger is always better* (for selection)."""
        return self.primary if self.higher_is_better else -self.primary


class ResearchAttempt(BaseModel):
    """One archived research-task attempt — kept apart from code/training attempts (Goal 09).

    Mirrors :class:`Attempt` and :class:`TrainingAttempt` but carries a generic
    :class:`MetricRecord` produced by the task's own ``eval.py``. ``family`` groups attempts
    so the suite summary can report per task family (algorithm / training / policy). Stored
    in ``runs/research_attempts.jsonl``; negative results — failed correctness, regressions,
    timeouts, gate rejections — are recorded with their ``status`` and ``reason``, never
    discarded.
    """

    attempt_id: str
    task_id: str
    family: str = ""
    candidate: Candidate
    metric: MetricRecord | None = None
    status: AttemptStatus = AttemptStatus.REJECTED
    reason: str = ""
    gates: GateReport | None = None
    created_at: datetime = Field(default_factory=_utcnow)


class TrainedModelArtifact(BaseModel):
    """A model-training (weight-update) artifact with full reproducible lineage (Goal 12).

    The output of a governed weight-update experiment: the produced ``weights`` plus the
    lineage needed to reproduce them (the base-model hash it started from, the fixed data id
    + seed it trained/validated on, the candidate ``train_config``, and the code version) and
    the held-out objective metric that scored it. Stored as an artifact and archived; a
    failed run is recorded too (``passed=False``). An artifact is **never** auto-bound to an
    agent role — deploying it is a separate, human-approved governance action.
    """

    artifact_id: str
    experiment_id: str
    base_model_hash: str
    data_id: str
    data_seed: int
    train_config: dict = Field(default_factory=dict)
    code_version: str = ""
    weights: list[float] = Field(default_factory=list)
    val_loss: float = 0.0
    passed: bool = False
    reproducible: bool = True
    reason: str = ""
    created_at: datetime = Field(default_factory=_utcnow)


class ModelDeployment(BaseModel):
    """A record of binding a trained model artifact to an agent role (Goal 12).

    Created only by an explicit, human-approved ``MODEL_DEPLOY`` governance action with
    cross-model review (the reviewer's provider differs from the role's implementation
    provider). A trained model never reaches a role without one of these on record.
    """

    deployment_id: str
    artifact_id: str
    role: str
    approver: str
    reviewer_provider: str
    implementation_provider: str
    created_at: datetime = Field(default_factory=_utcnow)


class ModelCall(BaseModel):
    """Audit-ledger row appended to ``runs/model_calls.jsonl`` for every model call.

    Populated once a real provider exists (Goal 02/07); defined now so the ledger
    format is stable and auditable from the start.
    """

    call_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    provider: str
    model: str
    prompt_hash: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    pricing_metadata: dict[str, object] = Field(default_factory=dict)
    experiment_id: str = ""
    role: str = ""
    provider_request_id: str = ""
    http_status: int | None = None
    retry_count: int = 0
    final_error_kind: str = ""
    provider_version: str = ""
    created_at: datetime = Field(default_factory=_utcnow)


class GovernedAction(str, Enum):
    """A capability escalation that may not happen without explicit human approval (Goal 10).

    This is exactly the bound set from ``docs/13_self_improvement_loop.md`` — the changes a
    self-improvement loop may *propose* but never *apply* on its own. The governance gate
    (``governance.py``) default-denies any of these unless a human-issued
    :class:`ApprovalDecision` is on record, bound to the exact proposed change.
    """

    BUDGET_INCREASE = "budget_increase"  # expand compute / token / USD budgets
    TIER_CHANGE = "tier_change"  # change deployment tier
    EGRESS_ALLOWLIST_CHANGE = "egress_allowlist_change"
    EVALUATOR_OR_TEST_CHANGE = "evaluator_or_test_change"
    SAFETY_GATE_CHANGE = "safety_gate_change"
    LOGGING_OR_AUDIT_CHANGE = "logging_or_audit_change"
    PERMISSION_EXPANSION = "permission_expansion"  # widen tool permissions / edit surface
    EXECUTION_PLANE_NETWORK = "execution_plane_network"
    AUTONOMOUS_INSTALL = "autonomous_install"
    MODEL_TRAIN = "model_train"  # run a weight-update experiment (Goal 12)
    MODEL_DEPLOY = "model_deploy"  # bind a trained model to an agent role (Goal 12)
    HIGH_RISK_ACTION = "high_risk_action"  # any other irreversible / high-budget action


class ApprovalScope(str, Enum):
    """How long a granted approval authorizes its action."""

    ONCE = "once"  # single-use: consumed the first time the action is authorized
    STANDING = "standing"  # reusable for the identical change until it expires or is revoked


class OperatorRole(str, Enum):
    """Human governance roles (Goal 19).

    Agents may request governed actions, but only active human operators with an approving
    role can grant, deny, revoke, or manage operator records.
    """

    REQUESTER = "requester"
    REVIEWER = "reviewer"
    APPROVER = "approver"
    ADMIN = "admin"


class OperatorStatus(str, Enum):
    """Whether an operator identity is usable for new governance records."""

    ACTIVE = "active"
    REVOKED = "revoked"


class OperatorIdentity(BaseModel):
    """Typed local operator identity for Tier 2 governance (Goal 19)."""

    operator_id: str
    display_name: str
    role: OperatorRole
    auth_method: str = "local"
    auth_metadata: dict[str, str] = Field(default_factory=dict)
    status: OperatorStatus = OperatorStatus.ACTIVE
    created_at: datetime = Field(default_factory=_utcnow)
    revoked_at: datetime | None = None

    @property
    def active(self) -> bool:
        return self.status is OperatorStatus.ACTIVE and self.revoked_at is None


class GovernancePolicy(BaseModel):
    """Policy template for one governed action (Goal 19)."""

    policy_id: str
    action: GovernedAction
    risk: str = "medium"
    required_reviewers: int = 1
    required_role: OperatorRole = OperatorRole.APPROVER
    separation_of_duties: bool = True
    max_scope: ApprovalScope = ApprovalScope.ONCE
    max_expiry_seconds: int | None = None
    require_signature: bool = True
    required_rationale_fields: list[str] = Field(default_factory=list)
    required_evidence: list[str] = Field(default_factory=list)


class ApprovalRequest(BaseModel):
    """A request for a human to approve a governed action (Goal 10).

    ``content_hash`` binds the request to the *exact* proposed change (action + target +
    payload). An :class:`ApprovalDecision` authorizes only the request with the matching
    hash, so an approval can never be reused for a different change. Recorded to
    ``runs/approvals.jsonl`` whether or not it is ever granted — every escalation stays
    auditable.
    """

    record: Literal["request"] = "request"
    request_id: str
    action: GovernedAction
    target: str = ""
    content_hash: str = ""
    actor: str = ""  # who/what raised it (an agent or the controller) — never approves
    rationale: str = ""
    payload: dict = Field(default_factory=dict)
    risk: str = "medium"
    evidence: list[str] = Field(default_factory=list)
    rollback_plan: str = ""
    scope: ApprovalScope = ApprovalScope.ONCE
    created_at: datetime = Field(default_factory=_utcnow)
    expires_at: datetime | None = None


class ApprovalDecision(BaseModel):
    """A human's decision on an :class:`ApprovalRequest` (Goal 10).

    Only a human issues this (there is no agent tool that can); ``approver`` records who.
    A granted, unexpired, unrevoked decision whose ``content_hash`` matches the action is
    the *only* thing that authorizes a governed action.
    """

    record: Literal["decision"] = "decision"
    decision_id: str
    request_id: str
    content_hash: str
    action: GovernedAction
    granted: bool
    approver: str  # human id — required; agents can never populate this
    operator_id: str = ""  # typed Goal 19 identity; empty means legacy Goal 10 decision
    signature: str = ""
    signature_payload_hash: str = ""
    signature_verified: bool = False
    legacy_approver: bool = False
    policy_id: str = ""
    scope: ApprovalScope = ApprovalScope.ONCE
    reason: str = ""
    created_at: datetime = Field(default_factory=_utcnow)
    expires_at: datetime | None = None


class ApprovalRevocation(BaseModel):
    """Revokes a previously-granted :class:`ApprovalDecision` (Goal 10).

    Also used to *consume* a single-use (``ONCE``) approval after it authorizes its action,
    so it cannot be replayed. Append-only, like everything in the ledger.
    """

    record: Literal["revocation"] = "revocation"
    revocation_id: str
    decision_id: str
    by: str = ""
    reason: str = ""
    created_at: datetime = Field(default_factory=_utcnow)


__all__ = [
    "AttemptStatus",
    "GateDecision",
    "GateResult",
    "GateReport",
    "GovernedAction",
    "ApprovalScope",
    "OperatorRole",
    "OperatorStatus",
    "OperatorIdentity",
    "GovernancePolicy",
    "ApprovalRequest",
    "ApprovalDecision",
    "ApprovalRevocation",
    "TrainedModelArtifact",
    "ModelDeployment",
    "TaskSpec",
    "Candidate",
    "EvaluationResult",
    "Attempt",
    "MemoryEntry",
    "MetricRecord",
    "ResearchAttempt",
    "WORST_VAL_LOSS",
    "TrainConfig",
    "TrainResult",
    "TrainingAttempt",
    "ModelCall",
    "ProcessConfig",
    "MetaChangeKind",
    "MetaRecommendation",
    "MetaMetrics",
    "MetaChange",
    "ABResult",
    "MetaChangeRecord",
]
