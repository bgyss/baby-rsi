from collections import Counter
from pathlib import Path

from siro.research import (
    discover_research_tasks,
    research_improves,
    run_research_eval,
    summarize_research,
)
from siro.sandbox import Sandbox
from siro.schemas import (
    AttemptStatus,
    Candidate,
    GateDecision,
    GateReport,
    GateResult,
    MetricRecord,
    ModelCall,
    ResearchAttempt,
)


def test_expanded_suite_has_required_task_counts_and_new_families():
    tasks = discover_research_tasks()
    counts = Counter(task.family for task in tasks)

    assert counts["algorithm"] >= 10
    assert counts["training"] >= 10
    assert counts["policy"] >= 10
    assert {"data_cleaning", "parser_validator"} <= set(counts)


def test_every_research_baseline_runs_to_typed_metric():
    sandbox = Sandbox()

    for task in discover_research_tasks():
        metric = run_research_eval(task, task.surface_code, sandbox)
        assert metric.primary_name == task.primary_name
        assert metric.higher_is_better is task.higher_is_better
        assert metric.error == "", f"{task.family}/{task.task_id}: {metric.error}"


def test_known_good_candidates_improve_representative_subset():
    sandbox = Sandbox()
    checked = 0

    for task in discover_research_tasks():
        good_path = Path(task.path) / "known_good" / task.edit_surface
        if not good_path.exists():
            continue
        baseline = run_research_eval(task, task.surface_code, sandbox)
        candidate = run_research_eval(task, good_path.read_text(encoding="utf-8"), sandbox)
        improves, reason = research_improves(candidate, baseline)
        assert improves, f"{task.family}/{task.task_id}: {reason}"
        checked += 1

    assert checked >= 10


def test_fast_but_wrong_candidate_cannot_improve():
    task = next(t for t in discover_research_tasks() if t.task_id == "top_k_sum")
    wrong = "def solve(values, k):\n    return 0\n"

    baseline = run_research_eval(task, task.surface_code, Sandbox())
    candidate = run_research_eval(task, wrong, Sandbox())
    improves, reason = research_improves(candidate, baseline)

    assert not improves
    assert "failed" in reason


def _attempt(
    family: str,
    task_id: str,
    code: str,
    *,
    primary: float,
    passed: bool,
    status: AttemptStatus,
    reason: str = "",
    gates: list[GateResult] | None = None,
    reproducible: bool | None = None,
) -> ResearchAttempt:
    metric = MetricRecord(
        primary_name="m",
        primary=primary,
        passed=passed,
        reproducible=passed if reproducible is None else reproducible,
    )
    return ResearchAttempt(
        attempt_id=f"{task_id}-{code[-1]}",
        task_id=task_id,
        family=family,
        candidate=Candidate(candidate_id=f"c-{code[-1]}", task_id=task_id, code=code),
        metric=metric,
        status=status,
        reason=reason,
        gates=GateReport(results=gates or []),
    )


def test_summarize_research_reports_goal17_fields():
    attempts = [
        _attempt("algorithm", "a", "code_a", primary=1.0, passed=True, status=AttemptStatus.PROMOTED),
        _attempt(
            "algorithm",
            "a",
            "code_b",
            primary=0.8,
            passed=True,
            status=AttemptStatus.REJECTED,
            reason="hidden tests failed",
            gates=[GateResult(gate="hidden_tests", decision=GateDecision.FAILED)],
        ),
        _attempt(
            "algorithm",
            "b",
            "code_c",
            primary=0.7,
            passed=False,
            status=AttemptStatus.REJECTED,
            reason="not reproducible",
            reproducible=False,
        ),
        _attempt(
            "algorithm",
            "b",
            "code_d",
            primary=0.0,
            passed=False,
            status=AttemptStatus.ERROR,
            gates=[GateResult(gate="safety", decision=GateDecision.FAILED)],
        ),
    ]
    ledger = [
        ModelCall(provider="anthropic", model="m", prompt_hash="h", input_tokens=10, output_tokens=5, cost_usd=2.0, experiment_id="a")
    ]

    summary = summarize_research(attempts, ledger_rows=ledger)["algorithm"]

    assert summary.accepted == 1
    assert summary.promoted == 1
    assert summary.mixed == 1
    assert summary.failed == 2
    assert summary.hidden_test_failures == 1
    assert summary.reproducibility_failures == 1
    assert summary.safety_gate_failures == 1
    assert summary.cost_per_promotion == 2.0
