"""Bounded operational pilot planning and reporting (Goal 20).

The pilot layer is deliberately a measurement harness, not a new execution engine. It fixes
the benchmark plan, records the exact commands/configs/ledgers used by each arm, and renders
a decision-quality report from objective research attempts plus the model-call ledger.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .archive import ModelCallLedger
from .research import ResearchArchive, summarize_research
from .schemas import AttemptStatus, ModelCall, ResearchAttempt

DEFAULT_PILOT_ID = "operational-pilot-v1"
DEFAULT_PILOT_ROOT = Path("runs/pilots") / DEFAULT_PILOT_ID
DEFAULT_PILOT_PLAN_PATH = DEFAULT_PILOT_ROOT / "pilot_plan.json"
DEFAULT_PILOT_REPORT_PATH = DEFAULT_PILOT_ROOT / "pilot_report.md"

DEFAULT_PILOT_TASKS = [
    "tasks/research/algorithm/pair_count",
    "tasks/research/training/tiny_mlp",
    "tasks/research/policy/sentiment_rules",
    "tasks/research/data_cleaning/normalize_emails",
    "tasks/research/parser_validator/slug_validator",
]


@dataclass(frozen=True)
class PilotArm:
    """One comparable pilot arm."""

    name: str
    tier: int
    config: str
    max_usd_per_run: float
    max_usd_per_day: float
    max_tokens_per_call: int
    required: bool = True
    condition: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PilotArm":
        return cls(
            name=str(data["name"]),
            tier=int(data["tier"]),
            config=str(data["config"]),
            max_usd_per_run=float(data["max_usd_per_run"]),
            max_usd_per_day=float(data["max_usd_per_day"]),
            max_tokens_per_call=int(data["max_tokens_per_call"]),
            required=bool(data.get("required", True)),
            condition=str(data.get("condition", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "tier": self.tier,
            "config": self.config,
            "max_usd_per_run": self.max_usd_per_run,
            "max_usd_per_day": self.max_usd_per_day,
            "max_tokens_per_call": self.max_tokens_per_call,
            "required": self.required,
            "condition": self.condition,
        }


@dataclass(frozen=True)
class PilotPlan:
    """Frozen benchmark plan for one operational pilot."""

    pilot_id: str
    tasks: list[str]
    arms: list[PilotArm]
    seeds: list[int]
    stop_conditions: list[str]
    expected_report_path: str

    @classmethod
    def default(cls, root: Path = DEFAULT_PILOT_ROOT) -> "PilotPlan":
        return cls(
            pilot_id=DEFAULT_PILOT_ID,
            tasks=list(DEFAULT_PILOT_TASKS),
            arms=[
                PilotArm(
                    name="tier0_local",
                    tier=0,
                    config="config/tier0.local.yaml",
                    max_usd_per_run=0.0,
                    max_usd_per_day=0.0,
                    max_tokens_per_call=0,
                ),
                PilotArm(
                    name="tier1_cheap_frontier",
                    tier=1,
                    config="config/tier1.cheap_frontier.yaml",
                    max_usd_per_run=2.0,
                    max_usd_per_day=10.0,
                    max_tokens_per_call=4000,
                ),
                PilotArm(
                    name="tier1_strong_frontier",
                    tier=1,
                    config="config/tier1.frontier.yaml",
                    max_usd_per_run=5.0,
                    max_usd_per_day=25.0,
                    max_tokens_per_call=8000,
                    condition="Run only if the cheap-frontier arm produces useful signal.",
                ),
            ],
            seeds=[0],
            stop_conditions=[
                "Halt if any arm exceeds max_usd_per_run or max_usd_per_day.",
                "Halt if execution-plane network, package install, evaluator edits, or safety-gate edits are requested.",
                "Halt if task set, provider config, or promotion rules would change mid-pilot.",
            ],
            expected_report_path=str(root / "pilot_report.md"),
        )

    @classmethod
    def from_path(cls, path: Path) -> "PilotPlan":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            pilot_id=str(data["pilot_id"]),
            tasks=[str(t) for t in data["tasks"]],
            arms=[PilotArm.from_dict(a) for a in data["arms"]],
            seeds=[int(s) for s in data.get("seeds", [0])],
            stop_conditions=[str(s) for s in data["stop_conditions"]],
            expected_report_path=str(data["expected_report_path"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "pilot_id": self.pilot_id,
            "tasks": self.tasks,
            "arms": [arm.to_dict() for arm in self.arms],
            "seeds": self.seeds,
            "stop_conditions": self.stop_conditions,
            "expected_report_path": self.expected_report_path,
        }

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )


@dataclass
class PilotArmSummary:
    arm: PilotArm
    attempts: list[ResearchAttempt]
    calls: list[ModelCall]
    status: str
    missing: list[str] = field(default_factory=list)
    budget_breaches: list[str] = field(default_factory=list)
    total_cycles: int = 0
    total_spend: float = 0.0
    total_tokens: int = 0
    pass_rate: float = 0.0
    promotion_rate: float = 0.0
    hidden_failure_rate: float = 0.0
    reproducibility_failure_rate: float = 0.0
    safety_escalation_rate: float = 0.0
    cost_per_promotion: float | None = None
    promoted: int = 0
    mixed: int = 0
    failed: int = 0
    common_failure_signatures: list[tuple[str, int]] = field(default_factory=list)
    cost_per_family: dict[str, float] = field(default_factory=dict)


def write_default_pilot_plan(path: Path = DEFAULT_PILOT_PLAN_PATH) -> PilotPlan:
    plan = PilotPlan.default(path.parent)
    plan.write(path)
    return plan


def command_transcript(plan: PilotPlan, root: Path) -> str:
    """Human-runnable command transcript for the frozen plan."""
    lines = [
        "# Operational Pilot Command Transcript",
        "",
        "Run each arm into its own immutable subdirectory. Do not edit configs, evaluators, hidden data, gates, or budgets mid-pilot.",
        "",
    ]
    for arm in plan.arms:
        lines.append(f"## {arm.name}")
        if arm.condition:
            lines.append(f"Condition: {arm.condition}")
        for task in plan.tasks:
            lines.append(
                "UV_CACHE_DIR=.uv-cache uv run siro run-research "
                f"{task} --config {arm.config} "
                f"--archive {root / arm.name / 'research_attempts.jsonl'} "
                f"--model-calls {root / arm.name / 'model_calls.jsonl'}"
            )
        lines.append("")
    lines.append(
        "UV_CACHE_DIR=.uv-cache uv run siro pilot-report "
        f"--plan {root / 'pilot_plan.json'} --output {plan.expected_report_path}"
    )
    return "\n".join(lines) + "\n"


def write_command_transcript(plan: PilotPlan, root: Path) -> Path:
    path = root / "command_transcript.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(command_transcript(plan, root), encoding="utf-8")
    return path


def archive_pilot_configs(plan: PilotPlan, root: Path) -> list[Path]:
    """Copy the exact provider/tier configs named by the plan into the pilot archive."""
    archived: list[Path] = []
    config_dir = root / "configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    for arm in plan.arms:
        source = Path(arm.config)
        destination = config_dir / f"{arm.name}.yaml"
        if source.exists():
            destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            destination.write_text(
                f"# missing config at pilot-init time: {source}\n", encoding="utf-8"
            )
        archived.append(destination)
    return archived


def _arm_paths(root: Path, arm: PilotArm) -> tuple[Path, Path]:
    base = root / arm.name
    return base / "research_attempts.jsonl", base / "model_calls.jsonl"


def _rate(numerator: int, denominator: int) -> float:
    return (numerator / denominator) if denominator else 0.0


def _attempts_for_plan(plan: PilotPlan, attempts: list[ResearchAttempt]) -> list[ResearchAttempt]:
    task_names = {Path(task).name for task in plan.tasks}
    return [attempt for attempt in attempts if attempt.task_id in task_names]


def _gate_failure(attempt: ResearchAttempt, needle: str) -> bool:
    if attempt.gates is None:
        return False
    return any(
        needle in result.gate and result.decision.value != "passed"
        for result in attempt.gates.results
    )


def _summarize_arm(plan: PilotPlan, root: Path, arm: PilotArm) -> PilotArmSummary:
    attempts_path, calls_path = _arm_paths(root, arm)
    missing = []
    if not attempts_path.exists():
        missing.append(str(attempts_path))
    if not calls_path.exists():
        missing.append(str(calls_path))

    attempts = (
        _attempts_for_plan(plan, ResearchArchive(attempts_path).read_all())
        if attempts_path.exists()
        else []
    )
    calls = ModelCallLedger(calls_path).read_all() if calls_path.exists() else []
    planned_task_ids = {Path(task).name for task in plan.tasks}
    observed_task_ids = {attempt.task_id for attempt in attempts}
    missing_tasks = sorted(planned_task_ids - observed_task_ids)
    missing.extend(f"task:{task_id}" for task_id in missing_tasks)

    total_spend = sum(call.cost_usd for call in calls)
    total_tokens = sum(call.input_tokens + call.output_tokens for call in calls)
    breaches = []
    if total_spend > arm.max_usd_per_day:
        breaches.append(
            f"total estimated spend ${total_spend:.4f} exceeds day cap ${arm.max_usd_per_day:.4f}"
        )
    for call in calls:
        tokens = call.input_tokens + call.output_tokens
        if arm.max_tokens_per_call > 0 and tokens > arm.max_tokens_per_call:
            breaches.append(
                f"call {call.call_id} exceeds token cap ({tokens}>{arm.max_tokens_per_call})"
            )
        if call.cost_usd > arm.max_usd_per_run:
            breaches.append(
                f"call {call.call_id} exceeds per-run spend cap (${call.cost_usd:.4f}>${arm.max_usd_per_run:.4f})"
            )

    cycles = len(attempts)
    promoted = sum(1 for attempt in attempts if attempt.status is AttemptStatus.PROMOTED)
    passed = sum(1 for attempt in attempts if attempt.metric is not None and attempt.metric.passed)
    mixed = sum(
        1
        for attempt in attempts
        if attempt.status is AttemptStatus.REJECTED
        and attempt.metric is not None
        and attempt.metric.passed
    )
    failed = (
        sum(
            1
            for attempt in attempts
            if attempt.status in {AttemptStatus.REJECTED, AttemptStatus.ERROR}
        )
        - mixed
    )
    hidden_failures = sum(
        1
        for attempt in attempts
        if _gate_failure(attempt, "hidden") or "hidden" in attempt.reason.lower()
    )
    reproducibility_failures = sum(
        1
        for attempt in attempts
        if _gate_failure(attempt, "reproducibility")
        or "reproduc" in attempt.reason.lower()
        or (
            attempt.metric is not None and attempt.metric.passed and not attempt.metric.reproducible
        )
    )
    safety_escalations = sum(
        1
        for attempt in attempts
        if _gate_failure(attempt, "safety") or "safety" in attempt.reason.lower()
    )
    failures = Counter(
        a.reason or a.status.value for a in attempts if a.status is not AttemptStatus.PROMOTED
    )
    family_summaries = summarize_research(attempts, ledger_rows=calls) if attempts else {}

    status = "ready"
    if missing:
        status = "missing-evidence"
    if breaches:
        status = "budget-breach"

    return PilotArmSummary(
        arm=arm,
        attempts=attempts,
        calls=calls,
        status=status,
        missing=missing,
        budget_breaches=breaches,
        total_cycles=cycles,
        total_spend=total_spend,
        total_tokens=total_tokens,
        pass_rate=_rate(passed, cycles),
        promotion_rate=_rate(promoted, cycles),
        hidden_failure_rate=_rate(hidden_failures, cycles),
        reproducibility_failure_rate=_rate(reproducibility_failures, cycles),
        safety_escalation_rate=_rate(safety_escalations, cycles),
        cost_per_promotion=(total_spend / promoted) if promoted else None,
        promoted=promoted,
        mixed=mixed,
        failed=failed,
        common_failure_signatures=failures.most_common(5),
        cost_per_family={family: summary.cost_usd for family, summary in family_summaries.items()},
    )


def pilot_summaries(plan: PilotPlan, root: Path) -> list[PilotArmSummary]:
    return [_summarize_arm(plan, root, arm) for arm in plan.arms]


def recommendation(summaries: list[PilotArmSummary]) -> str:
    if any(summary.budget_breaches for summary in summaries):
        return "stop"
    ready = [summary for summary in summaries if summary.status == "ready"]
    if len(ready) < 2:
        return "revise"
    baseline = next((summary for summary in ready if summary.arm.tier == 0), ready[0])
    frontier = [summary for summary in ready if summary.arm.tier > 0]
    if not frontier:
        return "revise"
    best_frontier = max(frontier, key=lambda summary: (summary.promoted, summary.promotion_rate))
    if (
        best_frontier.promoted > baseline.promoted
        and best_frontier.safety_escalation_rate <= baseline.safety_escalation_rate
        and best_frontier.reproducibility_failure_rate <= baseline.reproducibility_failure_rate
    ):
        return "continue"
    return "revise"


def render_pilot_report(plan: PilotPlan, root: Path, *, provider_reconciliation: str = "") -> str:
    summaries = pilot_summaries(plan, root)
    rec = recommendation(summaries)
    lines = [
        f"# Operational Pilot Report: {plan.pilot_id}",
        "",
        f"Recommendation: **{rec}**",
        "",
        "## Fixed Plan",
        "",
        "Tasks:",
        *[f"- `{task}`" for task in plan.tasks],
        "",
        "Stop conditions:",
        *[f"- {condition}" for condition in plan.stop_conditions],
        "",
        "## Arm Summary",
        "",
        "| Arm | Status | Cycles | Spend Estimate | Pass Rate | Promotion Rate | Hidden Failures | Repro Failures | Safety Escalations | Cost / Promotion |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for summary in summaries:
        cost_per = (
            "n/a" if summary.cost_per_promotion is None else f"${summary.cost_per_promotion:.4f}"
        )
        lines.append(
            f"| {summary.arm.name} | {summary.status} | {summary.total_cycles} | "
            f"${summary.total_spend:.4f} | {summary.pass_rate:.0%} | "
            f"{summary.promotion_rate:.0%} | {summary.hidden_failure_rate:.0%} | "
            f"{summary.reproducibility_failure_rate:.0%} | {summary.safety_escalation_rate:.0%} | {cost_per} |"
        )

    lines.extend(["", "## Accepted, Mixed, Failed", ""])
    for summary in summaries:
        lines.append(
            f"- `{summary.arm.name}`: accepted/promoted={summary.promoted}, "
            f"mixed/escalated={summary.mixed}, failed={summary.failed}"
        )

    lines.extend(["", "## Cost Per Family", ""])
    for summary in summaries:
        if not summary.cost_per_family:
            lines.append(f"- `{summary.arm.name}`: n/a")
            continue
        costs = ", ".join(
            f"{family}=${cost:.4f}" for family, cost in sorted(summary.cost_per_family.items())
        )
        lines.append(f"- `{summary.arm.name}`: {costs}")

    lines.extend(["", "## Common Failure Signatures", ""])
    for summary in summaries:
        if not summary.common_failure_signatures:
            lines.append(f"- `{summary.arm.name}`: none")
            continue
        failures = ", ".join(
            f"{reason} ({count})" for reason, count in summary.common_failure_signatures
        )
        lines.append(f"- `{summary.arm.name}`: {failures}")

    lines.extend(["", "## Budget And Evidence Checks", ""])
    for summary in summaries:
        if summary.missing:
            lines.append(f"- `{summary.arm.name}` missing evidence: {', '.join(summary.missing)}")
        if summary.budget_breaches:
            lines.append(
                f"- `{summary.arm.name}` budget breach: {'; '.join(summary.budget_breaches)}"
            )
        if not summary.missing and not summary.budget_breaches:
            lines.append(f"- `{summary.arm.name}`: evidence present; estimated spend within cap.")

    lines.extend(
        [
            "",
            "## Provider Dashboard Reconciliation",
            "",
            provider_reconciliation
            or "Not available; spend is labeled as an estimate from the model-call ledger.",
            "",
            "## Decision Evidence",
            "",
        ]
    )
    baseline = next((summary for summary in summaries if summary.arm.tier == 0), None)
    frontier = [
        summary for summary in summaries if summary.arm.tier > 0 and summary.status == "ready"
    ]
    if baseline is None or not frontier:
        lines.append("Comparable evidence is incomplete; do not recommend scale-up.")
    else:
        best = max(frontier, key=lambda summary: (summary.promoted, summary.promotion_rate))
        delta = best.promoted - baseline.promoted
        lines.append(
            f"Best frontier arm `{best.arm.name}` produced {best.promoted} promoted attempt(s) "
            f"versus Tier 0 `{baseline.arm.name}` with {baseline.promoted}; delta={delta}."
        )
        lines.append(
            "Frontier spend is considered materially useful only if promotions are objective, "
            "reproducible, safety-passing, and achieved without budget breach."
        )

    return "\n".join(lines) + "\n"


def write_pilot_report(
    plan_path: Path,
    output_path: Path | None = None,
    *,
    provider_reconciliation: str = "",
) -> str:
    plan = PilotPlan.from_path(plan_path)
    root = plan_path.parent
    report = render_pilot_report(plan, root, provider_reconciliation=provider_reconciliation)
    destination = output_path or Path(plan.expected_report_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(report, encoding="utf-8")
    return report


__all__ = [
    "DEFAULT_PILOT_ID",
    "DEFAULT_PILOT_ROOT",
    "DEFAULT_PILOT_PLAN_PATH",
    "DEFAULT_PILOT_REPORT_PATH",
    "DEFAULT_PILOT_TASKS",
    "PilotArm",
    "PilotPlan",
    "PilotArmSummary",
    "write_default_pilot_plan",
    "write_command_transcript",
    "archive_pilot_configs",
    "pilot_summaries",
    "render_pilot_report",
    "write_pilot_report",
    "recommendation",
]
