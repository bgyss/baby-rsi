"""Meta-research loop — the bounded outer loop that improves the process (Goal 05).

Covers the acceptance criteria: proposals stored separately from candidate attempts,
A/B on the same task set, promotion requires aggregate improvement, a rollback plan is
generated, and durable changes require the human-approval flag.
"""

import pytest

from siro.archive import JSONLArchive
from siro.controller import RunResult
from siro.meta import (
    MetaChangeStore,
    MetaResearcher,
    aggregate_metrics,
    apply_meta_change,
    forbidden_meta_change,
    propose_meta_change,
)
from siro.model_client import ScriptedModelClient
from siro.schemas import (
    Attempt,
    AttemptStatus,
    Candidate,
    EvaluationResult,
    GateDecision,
    GateReport,
    GateResult,
    MetaChange,
    MetaChangeKind,
    MetaChangeRecord,
    MetaRecommendation,
    ProcessConfig,
)

TASK_DIR = "tasks/code_improver/task_001"
GOOD_CODE = "def sum_list(values):\n    return sum(values)\n"
PASSING_RESPONSE = f"```python\n{GOOD_CODE}```"


def _attempt(attempt_id, *, score, status, reason="", code=GOOD_CODE, gates=None):
    return Attempt(
        attempt_id=attempt_id,
        task_id="t",
        candidate=Candidate(candidate_id=attempt_id, task_id="t", code=code),
        evaluation=EvaluationResult(passed_tests=4, score=score, reproducible=True),
        status=status,
        reason=reason,
        gates=gates,
    )


# --------------------------------------------------------------------------- #
# Propose + bounds.
# --------------------------------------------------------------------------- #


def test_propose_is_a_bounded_reversible_delta(tmp_path):
    archive = JSONLArchive(tmp_path / "attempts.jsonl")
    archive.append(_attempt("a1", score=-300.0, status=AttemptStatus.REJECTED, reason="3 test(s) failing"))

    proposal = propose_meta_change(archive)

    # An *allowed* kind, never a forbidden one.
    assert proposal.kind == MetaChangeKind.RETRIEVAL_STRATEGY
    assert proposal.bounds_ok
    # A fully-specified, reversible config delta.
    assert proposal.candidate_config.retrieval_limit > proposal.baseline_config.retrieval_limit
    # A rollback plan is generated (acceptance criterion).
    assert proposal.rollback_plan
    assert str(proposal.baseline_config.retrieval_limit) in proposal.rollback_plan
    # The rationale reflects on the archive's bottleneck.
    assert "test_failures" in proposal.rationale


def test_forbidden_surfaces_are_flagged():
    ok, _ = forbidden_meta_change("memory.retrieval_limit", "surface more lessons")
    assert ok
    for target in ("safety.gate_threshold", "evaluator.weights", "budget.usd_per_day", "egress allowlist"):
        flagged_ok, reason = forbidden_meta_change(target, "tweak it")
        assert not flagged_ok
        assert reason


def test_forbidden_proposal_is_recorded_and_rejected_without_ab(tmp_path):
    archive = JSONLArchive(tmp_path / "attempts.jsonl")
    store = MetaChangeStore(tmp_path / "meta_changes.jsonl")
    researcher = MetaResearcher(archive=archive, store=store, benchmark_tasks=[TASK_DIR])

    # Force an out-of-bounds proposal by monkeypatching the proposer's output.
    forbidden = MetaChange(
        meta_change_id="x1",
        kind=MetaChangeKind.SCORING_HEURISTIC,
        target="evaluator.weights",
        description="weaken the evaluator scoring",
        rationale="...",
        baseline_config=ProcessConfig(),
        candidate_config=ProcessConfig(),
        rollback_plan="revert",
        bounds_ok=False,
        forbidden_reason="touches forbidden surface 'evaluator'",
    )
    researcher.propose = lambda baseline=None: forbidden  # type: ignore[assignment]

    record = researcher.run(model_factory=lambda: ScriptedModelClient([PASSING_RESPONSE]))
    assert record.recommendation is MetaRecommendation.REJECT
    assert record.ab_result is None  # never validated
    assert "forbidden" in record.reason


# --------------------------------------------------------------------------- #
# Aggregate metrics.
# --------------------------------------------------------------------------- #


def test_aggregate_metrics_over_runs():
    seed = _attempt("seed", score=100.0, status=AttemptStatus.PROMOTED, reason="all tests passing")
    win = _attempt("win", score=900.0, status=AttemptStatus.PROMOTED, reason="all tests passing")
    bad = _attempt("bad", score=-300.0, status=AttemptStatus.REJECTED, reason="3 test(s) failing")
    bad.evaluation.failed_tests = 3
    run = RunResult(task_id="t", attempts=[seed, win, bad], best=win)

    metrics = aggregate_metrics([run])
    assert metrics.n_runs == 1
    assert metrics.n_attempts == 3
    # seed + win pass, bad fails -> 2/3.
    assert metrics.pass_rate == pytest.approx(2 / 3)
    # First clean pass is the seed at generation 0.
    assert metrics.median_generations_to_success == 0.0
    assert metrics.safety_gate_failures == 0


def test_aggregate_counts_safety_failures():
    failed_safety = GateReport(
        results=[GateResult(gate="safety", decision=GateDecision.FAILED, findings=["network"])]
    )
    seed = _attempt("seed", score=100.0, status=AttemptStatus.PROMOTED, reason="all tests passing")
    blocked = _attempt("blk", score=0.0, status=AttemptStatus.REJECTED, gates=failed_safety)
    run = RunResult(task_id="t", attempts=[seed, blocked], best=seed)
    assert aggregate_metrics([run]).safety_gate_failures == 1


# --------------------------------------------------------------------------- #
# A/B validation + separate storage.
# --------------------------------------------------------------------------- #


def test_ab_validation_stores_separately_with_rollback(tmp_path):
    attempts_path = tmp_path / "attempts.jsonl"
    store_path = tmp_path / "meta_changes.jsonl"
    archive = JSONLArchive(attempts_path)
    archive.append(_attempt("a1", score=-300.0, status=AttemptStatus.REJECTED, reason="3 test(s) failing"))
    store = MetaChangeStore(store_path)

    researcher = MetaResearcher(
        archive=archive, store=store, benchmark_tasks=[TASK_DIR], generations=2
    )
    record = researcher.run(
        model_factory=lambda: ScriptedModelClient([PASSING_RESPONSE])
    )

    # Stored in the separate meta-change archive, not the attempts archive.
    assert len(store) == 1
    assert len(archive.read_all()) == 1  # A/B did not pollute the real attempts archive
    # The A/B compared old vs new on the same fixed task set.
    assert record.ab_result is not None
    assert record.ab_result.benchmark_tasks == [TASK_DIR]
    assert record.ab_result.generations == 2
    # Rollback plan is on the persisted record.
    persisted = store.read_all()[0]
    assert persisted.proposal.rollback_plan
    # Loop only recommends; approval stays False until a human sets it.
    assert persisted.approved is False
    assert persisted.recommendation in (MetaRecommendation.PROMOTE, MetaRecommendation.REJECT)


# --------------------------------------------------------------------------- #
# Human-approval gate on durable application.
# --------------------------------------------------------------------------- #


def _promote_record(approved=False):
    proposal = MetaChange(
        meta_change_id="m1",
        kind=MetaChangeKind.RETRIEVAL_STRATEGY,
        target="memory.retrieval_limit",
        description="bump",
        rationale="...",
        baseline_config=ProcessConfig(retrieval_limit=5),
        candidate_config=ProcessConfig(retrieval_limit=8),
        rollback_plan="revert to 5",
    )
    return MetaChangeRecord(
        record_id="r1",
        proposal=proposal,
        recommendation=MetaRecommendation.PROMOTE,
        approved=approved,
    )


def test_apply_requires_human_approval():
    record = _promote_record(approved=False)
    with pytest.raises(PermissionError):
        apply_meta_change(record)

    record.approved = True
    new_config = apply_meta_change(record)
    assert new_config.retrieval_limit == 8


def test_apply_refuses_non_promoted():
    record = _promote_record(approved=True)
    record.recommendation = MetaRecommendation.REJECT
    with pytest.raises(PermissionError):
        apply_meta_change(record)
