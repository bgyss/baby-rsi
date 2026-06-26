from __future__ import annotations

import json
from pathlib import Path

from siro.archive import ModelCallLedger
from siro.cli import main
from siro.pilot import (
    PilotPlan,
    render_pilot_report,
    write_command_transcript,
    write_default_pilot_plan,
)
from siro.research import ResearchArchive
from siro.schemas import AttemptStatus, Candidate, MetricRecord, ModelCall, ResearchAttempt


def _attempt(
    task_id: str, family: str, status: AttemptStatus, *, reason: str = ""
) -> ResearchAttempt:
    return ResearchAttempt(
        attempt_id=f"{task_id}-{status.value}",
        task_id=task_id,
        family=family,
        candidate=Candidate(
            candidate_id=f"cand-{task_id}", task_id=task_id, code="def solve(): pass"
        ),
        metric=MetricRecord(
            primary_name="score",
            primary=1.0 if status is AttemptStatus.PROMOTED else 0.5,
            higher_is_better=True,
            passed=status is not AttemptStatus.ERROR,
            reproducible=status is AttemptStatus.PROMOTED,
        ),
        status=status,
        reason=reason,
    )


def _call(task_id: str, cost: float = 0.1) -> ModelCall:
    return ModelCall(
        provider="openai",
        model="pilot-model",
        prompt_hash=f"h-{task_id}",
        input_tokens=100,
        output_tokens=50,
        cost_usd=cost,
        experiment_id=task_id,
        role="implementation",
    )


def _write_arm(
    root: Path, arm: str, attempts: list[ResearchAttempt], calls: list[ModelCall]
) -> None:
    archive = ResearchArchive(root / arm / "research_attempts.jsonl")
    ledger = ModelCallLedger(root / arm / "model_calls.jsonl")
    for attempt in attempts:
        archive.append(attempt)
    for call in calls:
        ledger.append(call)


def test_default_pilot_plan_and_transcript_are_fixed(tmp_path):
    plan_path = tmp_path / "pilot_plan.json"
    plan = write_default_pilot_plan(plan_path)
    transcript = write_command_transcript(plan, tmp_path)

    data = json.loads(plan_path.read_text(encoding="utf-8"))
    assert data["pilot_id"] == "operational-pilot-v1"
    assert len(data["tasks"]) == 5
    assert [arm["name"] for arm in data["arms"]] == [
        "tier0_local",
        "tier1_cheap_frontier",
        "tier1_strong_frontier",
    ]
    text = transcript.read_text(encoding="utf-8")
    assert "config/tier0.local.yaml" in text
    assert "config/tier1.cheap_frontier.yaml" in text
    assert "pilot-report" in text


def test_pilot_report_compares_arms_and_computes_cost_per_promotion(tmp_path):
    plan = PilotPlan.default(tmp_path)
    plan_path = tmp_path / "pilot_plan.json"
    plan.write(plan_path)

    tasks = [Path(task).name for task in plan.tasks]
    for arm in plan.arms:
        attempts = [
            _attempt(tasks[0], "algorithm", AttemptStatus.PROMOTED),
            _attempt(tasks[1], "training", AttemptStatus.REJECTED, reason="hidden regression"),
            _attempt(tasks[2], "policy", AttemptStatus.ERROR, reason="safety escalation"),
            _attempt(tasks[3], "data_cleaning", AttemptStatus.PROMOTED),
            _attempt(
                tasks[4], "parser_validator", AttemptStatus.REJECTED, reason="not reproducible"
            ),
        ]
        calls = [_call(task, cost=0.2 if arm.tier > 0 else 0.0) for task in tasks]
        _write_arm(tmp_path, arm.name, attempts, calls)

    report = render_pilot_report(
        plan, tmp_path, provider_reconciliation="Dashboard total matches ledger."
    )

    assert "Recommendation:" in report
    assert "tier0_local" in report
    assert "tier1_cheap_frontier" in report
    assert "tier1_strong_frontier" in report
    assert "Cost / Promotion" in report
    assert "$0.5000" in report
    assert "Dashboard total matches ledger." in report
    assert "accepted/promoted=2, mixed/escalated=2, failed=1" in report
    assert "safety escalation" in report


def test_pilot_report_flags_missing_evidence_and_budget_breach(tmp_path):
    plan = PilotPlan.default(tmp_path)
    plan_path = tmp_path / "pilot_plan.json"
    plan.write(plan_path)
    task = Path(plan.tasks[0]).name
    _write_arm(
        tmp_path,
        "tier1_cheap_frontier",
        [_attempt(task, "algorithm", AttemptStatus.PROMOTED)],
        [_call(task, cost=20.0)],
    )

    assert (
        main(["pilot-report", "--plan", str(plan_path), "--output", str(tmp_path / "report.md")])
        == 2
    )
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "budget breach" in report
    assert "missing evidence" in report


def test_pilot_init_cli_writes_plan_and_transcript(tmp_path):
    assert main(["pilot-init", "--root", str(tmp_path)]) == 0
    assert (tmp_path / "pilot_plan.json").exists()
    assert (tmp_path / "command_transcript.md").exists()
    assert (tmp_path / "configs" / "tier0_local.yaml").exists()
    assert (tmp_path / "configs" / "tier1_cheap_frontier.yaml").exists()
    assert (tmp_path / "configs" / "tier1_strong_frontier.yaml").exists()


def test_pilot_run_rejects_unknown_arm_without_running_models(tmp_path):
    plan = PilotPlan.default(tmp_path)
    plan_path = tmp_path / "pilot_plan.json"
    plan.write(plan_path)
    assert main(["pilot-run", "--plan", str(plan_path), "--arm", "nope"]) == 2
