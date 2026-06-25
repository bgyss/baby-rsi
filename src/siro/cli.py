"""``siro`` command-line interface.

The canonical interface to the system (``docs/10_repo_structure.md``); ``mise``
tasks are thin wrappers. Goal 01 ships the command *surface* the self-improvement
cycle uses:

- ``run-task``            — run the per-task improvement loop (Goal 02).
- ``run-training``        — run the tiny-training improvement loop (Goal 06).
- ``run-org``             — run one full frontier-org research cycle (Goal 08).
- ``run-research``        — run the org on research-shaped task(s) (Goal 09).
- ``summarize-runs``      — reflect on the archive (real: counts + pass rate + best).
- ``summarize-research``  — per-family summary of the research suite (Goal 09).
- ``propose-meta-change`` — propose a process change (Goal 05).

Uses only the standard library ``argparse`` to keep Tier 0 dependency-light.
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from . import __version__
from .archive import JSONLArchive, ModelCallLedger
from .budget import BudgetExceeded, BudgetTracker
from .config import DEFAULT_CONFIG_PATH, load_config
from .controller import Controller, select_best
from .memory import ResearchMemory, failure_signature
from .meta import MetaChangeStore, MetaResearcher
from .model_client import LocalOpenAIClient
from .orchestrator import Orchestrator
from .providers import ModelClient
from .research import (
    DEFAULT_RESEARCH_ATTEMPTS_PATH,
    DEFAULT_RESEARCH_TASKS_DIR,
    ResearchArchive,
    discover_research_tasks,
    summarize_research,
)
from .schemas import MetaChangeRecord, MetaRecommendation
from .training import (
    DEFAULT_BUDGET_SECONDS,
    DEFAULT_TRAINING_ATTEMPTS_PATH,
    TrainingArchive,
    TrainingController,
)


def _build_runtime(
    args: argparse.Namespace, ledger: ModelCallLedger, role: str
) -> tuple[ModelClient, BudgetTracker | None, str]:
    """Resolve the model client + budget for a run from config (Goal 07).

    Tier and provider come from the config file alone — lowering tier back to 0 needs
    no code change. ``--config`` defaults to the safe Tier 0 (local) posture; if the
    file is missing we fall back to a bare local client so Tier 0 always works.
    """
    config_path = getattr(args, "config", None) or DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return LocalOpenAIClient(), None, f"tier 0 (local default; {config_path} not found)"
    config = load_config(config_path)
    model = config.client_for_role(role)
    budget = None if config.budget.unbounded else BudgetTracker(config.budget, ledger=ledger)
    label = f"tier {config.tier} (role {role} -> {getattr(model, 'provider', '?')}:" \
            f"{getattr(model, 'model', '?')})"
    return model, budget, label


def _cmd_run_task(args: argparse.Namespace) -> int:
    ledger = ModelCallLedger(args.model_calls)
    model, budget, label = _build_runtime(args, ledger, role="implementation")
    controller = Controller(
        archive=JSONLArchive(args.archive),
        ledger=ledger,
        memory=ResearchMemory(args.memory),
        budget=budget,
    )
    print(f"config: {label}")
    try:
        result = controller.run_task(args.task_dir, model=model, generations=args.generations)
    except BudgetExceeded as exc:
        print(f"HALTED — budget ceiling breached ({exc.kind}): {exc}")
        print("Escalation required: a human must approve raising the ceiling (config-only).")
        return 2

    print(f"run-task: {args.task_dir}  ({args.generations} generation(s))")
    for attempt in result.attempts:
        ev = attempt.evaluation
        print(
            f"  {attempt.candidate.candidate_id:>12}  "
            f"score={ev.score:>9.1f}  "
            f"pass={ev.passed_tests} fail={ev.failed_tests}  "
            f"{attempt.status.value:<8} {attempt.reason}"
        )
    best = result.best
    if best is not None:
        print(f"Best: {best.candidate.candidate_id} score={best.evaluation.score:.1f}")
        print(f"Archived {len(result.attempts)} attempt(s) to {args.archive}")
    return 0


def _cmd_run_training(args: argparse.Namespace) -> int:
    ledger = ModelCallLedger(args.model_calls)
    model, token_budget, label = _build_runtime(args, ledger, role="implementation")
    controller = TrainingController(
        archive=TrainingArchive(args.archive),
        ledger=ledger,
        budget_seconds=args.budget,
        budget=token_budget,
    )
    print(f"config: {label}")
    try:
        result = controller.run_training(
            args.task_dir, model=model, generations=args.generations
        )
    except BudgetExceeded as exc:
        print(f"HALTED — budget ceiling breached ({exc.kind}): {exc}")
        print("Escalation required: a human must approve raising the ceiling (config-only).")
        return 2

    print(
        f"run-training: {args.task_dir}  "
        f"({args.generations} generation(s), {args.budget:g}s budget each)"
    )
    for attempt in result.attempts:
        r = attempt.result
        val = f"{r.val_loss:.6f}" if r and r.reproducible else "   n/a  "
        thr = f"{r.throughput:>8.0f}" if r and r.reproducible else "     n/a"
        print(
            f"  {attempt.attempt_id:>12}  val_loss={val}  "
            f"thr={thr}/s  {attempt.status.value:<8} {attempt.reason}"
        )
    best = result.best
    if best is not None and best.result is not None:
        print(f"Best: {best.attempt_id} val_loss={best.result.val_loss:.6f}")
        print(f"Archived {len(result.attempts)} training attempt(s) to {args.archive}")
    return 0


def _cmd_run_org(args: argparse.Namespace) -> int:
    """Run one full frontier-organization research cycle on a task (Goal 08).

    Binds every role to its provider from the tier config (Tier 0 = all local; Tier 1 =
    frontier reasoning + a different-provider safety reviewer). Lowering the tier is
    config-only — no code change. Needs the model server / API keys the config selects.
    """
    config = load_config(args.config)
    ledger = ModelCallLedger(args.model_calls)
    budget = None if config.budget.unbounded else BudgetTracker(config.budget, ledger=ledger)
    orchestrator = Orchestrator.from_config(
        config,
        memory=ResearchMemory(args.memory),
        archive=JSONLArchive(args.archive),
        ledger=ledger,
        budget=budget,
    )
    print(f"config: tier {config.tier} ({args.config}); cross-model review: "
          f"{'required' if orchestrator.require_cross_model else 'not required (all-local)'}")
    try:
        result = orchestrator.run_cycle(args.objective, args.task_dir)
    except BudgetExceeded as exc:
        print(f"HALTED — budget ceiling breached ({exc.kind}): {exc}")
        print("Escalation required: a human must approve raising the ceiling (config-only).")
        return 2

    print(f"run-org: {args.task_dir}  objective={args.objective!r}")
    for role in result.agent_outputs:
        agent_result = result.agent_outputs[role]
        provider = agent_result.response.provider or "?"
        print(f"  {role:>15}  [{provider}]")
    decision = result.promotion_decision.value
    print(f"Promotion decision: {decision.upper()}  (attempt {result.attempt.attempt_id})")
    if result.attempt.evaluation is not None:
        ev = result.attempt.evaluation
        print(f"  objective: score={ev.score:.1f} pass={ev.passed_tests} fail={ev.failed_tests}")
    for escalation in result.escalations:
        print(f"  ESCALATION: {escalation}")
    if result.next_actions:
        print(f"  next: {'; '.join(result.next_actions)}")
    print(f"Recorded 1 attempt to {args.archive} and memory to {args.memory}.")
    return 0


def _cmd_run_research(args: argparse.Namespace) -> int:
    """Run the full org on research-shaped task(s) (Goal 09).

    With a ``task_dir`` it runs one cycle on that task; with none it runs one cycle on every
    task discovered under ``tasks/research/`` — so "the Tier 1 org runs a full lifecycle on
    each task family" is one command. Promotion is decided by each task's own ``eval.py``
    (the objective evaluator), not by any model. Lowering the tier is config-only.
    """
    config = load_config(args.config)
    ledger = ModelCallLedger(args.model_calls)
    budget = None if config.budget.unbounded else BudgetTracker(config.budget, ledger=ledger)
    orchestrator = Orchestrator.from_config(
        config,
        memory=ResearchMemory(args.memory),
        ledger=ledger,
        budget=budget,
        research_archive=ResearchArchive(args.archive),
    )
    if args.task_dir is not None:
        tasks = [args.task_dir]
    else:
        discovered = discover_research_tasks(args.tasks_root)
        if not discovered:
            print(f"No research tasks found under {args.tasks_root}.")
            return 0
        tasks = [Path(t.path) for t in discovered]

    print(f"config: tier {config.tier} ({args.config}); cross-model review: "
          f"{'required' if orchestrator.require_cross_model else 'not required (all-local)'}")
    print(f"run-research: {len(tasks)} task(s), objective={args.objective!r}")
    for task_dir in tasks:
        try:
            result = orchestrator.run_research_cycle(args.objective, task_dir)
        except BudgetExceeded as exc:
            print(f"HALTED — budget ceiling breached ({exc.kind}): {exc}")
            print("Escalation required: a human must approve raising the ceiling (config-only).")
            return 2
        metric = result.metric
        primary = (
            f"{metric.primary_name}={metric.primary:g} passed={metric.passed}"
            if metric is not None
            else "(not evaluated)"
        )
        print(
            f"  [{result.family:>9}] {result.task_id:<16} "
            f"{result.promotion_decision.value.upper():<9} {primary}"
        )
        for escalation in result.escalations:
            print(f"      ESCALATION: {escalation}")
    print(f"Recorded research attempts to {args.archive} and memory to {args.memory}.")
    return 0


def _cmd_summarize_research(args: argparse.Namespace) -> int:
    """Per-family suite summary (Goal 09 acceptance): pass rate, median cycles to success,
    safety-gate failures, token/USD spend, and strategy diversity."""
    attempts = ResearchArchive(args.path).read_all()
    if not attempts:
        print(f"No research attempts found in {args.path}.")
        return 0
    ledger_rows = ModelCallLedger(args.model_calls).read_all() if args.model_calls.exists() else []
    summaries = summarize_research(attempts, ledger_rows=ledger_rows)

    print(f"Research attempts: {len(attempts)}  (from {args.path})")
    for family, s in summaries.items():
        cycles = (
            f"{s.median_cycles_to_success:.1f}"
            if s.median_cycles_to_success is not None
            else "n/a"
        )
        print(f"\n[{family}]  tasks: {', '.join(s.task_ids)}")
        print(f"  attempts={s.attempts}  promoted={s.promoted}  pass_rate={s.pass_rate:.0%}")
        print(f"  median cycles to success: {cycles}")
        print(f"  safety-gate failures: {s.safety_gate_failures}")
        print(f"  spend: {s.tokens} tokens  ${s.cost_usd:.4f}")
        print(f"  strategy diversity: {s.strategy_diversity:.0%}  (distinct candidates / attempts)")
    return 0


def _cmd_summarize_runs(args: argparse.Namespace) -> int:
    archive = JSONLArchive(args.path)
    attempts = archive.read_all()
    if not attempts:
        print(f"No attempts found in {args.path}.")
        return 0

    status_counts = Counter(a.status.value for a in attempts)
    evaluated = [a for a in attempts if a.evaluation is not None]
    total_tests = sum(a.evaluation.passed_tests + a.evaluation.failed_tests for a in evaluated)
    passed_tests = sum(a.evaluation.passed_tests for a in evaluated)
    pass_rate = (passed_tests / total_tests) if total_tests else 0.0
    best = select_best(attempts)

    print(f"Attempts: {len(attempts)}  (from {args.path})")
    for status, count in sorted(status_counts.items()):
        print(f"  {status}: {count}")
    print(f"Test pass rate: {pass_rate:.1%}  ({passed_tests}/{total_tests})")
    if best is not None:
        print(f"Best score: {best.evaluation.score:.1f}  (attempt {best.attempt_id})")

    # Top recurring failure modes — reflect on negative results (Goal 03).
    failure_modes = Counter(
        failure_signature(a.reason) for a in attempts if failure_signature(a.reason) != "none"
    )
    if failure_modes:
        print("Top failure modes:")
        for signature, count in failure_modes.most_common(5):
            print(f"  {signature}: {count}")
    return 0


def _print_meta_change(record: MetaChangeRecord) -> None:
    """Render a meta-change record: the proposal, A/B deltas, and the gating reminder."""
    proposal = record.proposal
    print(f"Proposed meta-change [{proposal.kind.value}] target={proposal.target}")
    print(f"  {proposal.description}")
    print(f"  Rationale: {proposal.rationale}")
    print(f"  Rollback:  {proposal.rollback_plan}")
    if not proposal.bounds_ok:
        print(f"  BOUNDS: out of bounds — {proposal.forbidden_reason} (cannot be applied)")

    ab = record.ab_result
    if ab is not None:
        print(f"A/B on {len(ab.benchmark_tasks)} task(s), {ab.generations} generation(s) each:")
        print(
            f"  pass_rate            {ab.baseline.pass_rate:.0%} -> {ab.candidate.pass_rate:.0%}"
            f"  (Δ {ab.deltas['pass_rate']:+.2f})"
        )
        print(
            f"  median gens->success {ab.baseline.median_generations_to_success:.1f} -> "
            f"{ab.candidate.median_generations_to_success:.1f}"
            f"  (Δ {ab.deltas['median_generations_to_success']:+.1f})"
        )
        print(
            f"  invalid candidates   {ab.baseline.invalid_candidates} -> "
            f"{ab.candidate.invalid_candidates}"
        )
        print(
            f"  safety gate failures {ab.baseline.safety_gate_failures} -> "
            f"{ab.candidate.safety_gate_failures}"
        )
        print(
            f"  score/generation     {ab.baseline.score_improvement_per_generation:.1f} -> "
            f"{ab.candidate.score_improvement_per_generation:.1f}"
        )

    print(f"Recommendation: {record.recommendation.value} — {record.reason}")
    if record.recommendation is MetaRecommendation.PROMOTE:
        print("Durable application is human-gated: set approved=True before applying.")
    print("Reminder: meta-changes are proposals only; promotion is human-gated.")


def _cmd_propose_meta_change(args: argparse.Namespace) -> int:
    archive = JSONLArchive(args.path)
    store = MetaChangeStore(args.store)
    researcher = MetaResearcher(
        archive=archive,
        store=store,
        benchmark_tasks=list(args.benchmark),
        generations=args.generations,
    )
    print(f"propose-meta-change: read {len(archive.read_all())} attempt(s) from {args.path}")

    if args.validate:
        record = researcher.run(model_factory=lambda: LocalOpenAIClient())
    else:
        # Propose + record without running A/B (no model server needed). The record is
        # stored as a pending rejection until validation runs — proposals are kept
        # separately and audited either way.
        proposal = researcher.propose()
        record = MetaChangeRecord(
            record_id=proposal.meta_change_id,
            proposal=proposal,
            recommendation=MetaRecommendation.REJECT,
            reason="A/B validation not run (pass --validate to A/B on the benchmark)",
        )
        store.append(record)

    _print_meta_change(record)
    print(f"Recorded meta-change to {store.path} (separate from candidate attempts).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="siro",
        description="Bounded, auditable self-improving research organization testbed.",
    )
    parser.add_argument("--version", action="version", version=f"siro {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run-task", help="Run the per-task improvement loop (Goal 02).")
    p_run.add_argument("task_dir", type=Path, help="Path to a task directory.")
    p_run.add_argument(
        "-n", "--generations", type=int, default=5, help="Number of generations (default: 5)."
    )
    p_run.add_argument(
        "--archive",
        type=Path,
        default=Path("runs/attempts.jsonl"),
        help="Attempts archive path (default: runs/attempts.jsonl).",
    )
    p_run.add_argument(
        "--model-calls",
        type=Path,
        default=Path("runs/model_calls.jsonl"),
        help="Model-call audit ledger path (default: runs/model_calls.jsonl).",
    )
    p_run.add_argument(
        "--memory",
        type=Path,
        default=Path("runs/memory.jsonl"),
        help="Research-memory path (default: runs/memory.jsonl).",
    )
    p_run.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Tier/provider config (default: {DEFAULT_CONFIG_PATH}). Selecting tier is "
        "config-only — no code change.",
    )
    p_run.set_defaults(func=_cmd_run_task)

    p_train = sub.add_parser(
        "run-training", help="Run the tiny-training improvement loop (Goal 06)."
    )
    p_train.add_argument(
        "task_dir",
        type=Path,
        nargs="?",
        default=Path("tasks/training/task_001"),
        help="Path to a training task directory (default: tasks/training/task_001).",
    )
    p_train.add_argument(
        "-n", "--generations", type=int, default=5, help="Number of generations (default: 5)."
    )
    p_train.add_argument(
        "--budget",
        type=float,
        default=DEFAULT_BUDGET_SECONDS,
        help=f"Fixed wall-clock budget per candidate, seconds (default: {DEFAULT_BUDGET_SECONDS:g}).",
    )
    p_train.add_argument(
        "--archive",
        type=Path,
        default=DEFAULT_TRAINING_ATTEMPTS_PATH,
        help="Training-attempts archive path (default: runs/training_attempts.jsonl).",
    )
    p_train.add_argument(
        "--model-calls",
        type=Path,
        default=Path("runs/model_calls.jsonl"),
        help="Model-call audit ledger path (default: runs/model_calls.jsonl).",
    )
    p_train.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Tier/provider config (default: {DEFAULT_CONFIG_PATH}).",
    )
    p_train.set_defaults(func=_cmd_run_training)

    p_org = sub.add_parser(
        "run-org", help="Run one full frontier-org research cycle (Goal 08)."
    )
    p_org.add_argument(
        "task_dir",
        type=Path,
        nargs="?",
        default=Path("tasks/code_improver/task_001"),
        help="Path to a task directory (default: tasks/code_improver/task_001).",
    )
    p_org.add_argument(
        "--objective",
        default="Improve the task implementation against its objective metric.",
        help="The human research objective the organization works toward.",
    )
    p_org.add_argument(
        "--config",
        type=Path,
        default=Path("config/tier1.frontier.yaml"),
        help="Tier/provider config (default: config/tier1.frontier.yaml). "
        "Use config/tier0.local.yaml to run the same org fully local — config-only.",
    )
    p_org.add_argument(
        "--archive",
        type=Path,
        default=Path("runs/attempts.jsonl"),
        help="Attempts archive path (default: runs/attempts.jsonl).",
    )
    p_org.add_argument(
        "--model-calls",
        type=Path,
        default=Path("runs/model_calls.jsonl"),
        help="Model-call audit ledger path (default: runs/model_calls.jsonl).",
    )
    p_org.add_argument(
        "--memory",
        type=Path,
        default=Path("runs/memory.jsonl"),
        help="Research-memory path (default: runs/memory.jsonl).",
    )
    p_org.set_defaults(func=_cmd_run_org)

    p_research = sub.add_parser(
        "run-research",
        help="Run the full org on research-shaped task(s) (Goal 09).",
    )
    p_research.add_argument(
        "task_dir",
        type=Path,
        nargs="?",
        default=None,
        help="A research task dir. Omit to run one cycle on every task under tasks/research/.",
    )
    p_research.add_argument(
        "--objective",
        default="Improve the task against its objective metric.",
        help="The human research objective the organization works toward.",
    )
    p_research.add_argument(
        "--config",
        type=Path,
        default=Path("config/tier1.frontier.yaml"),
        help="Tier/provider config (default: config/tier1.frontier.yaml). "
        "Use config/tier0.local.yaml to run the same org fully local — config-only.",
    )
    p_research.add_argument(
        "--tasks-root",
        type=Path,
        default=DEFAULT_RESEARCH_TASKS_DIR,
        help=f"Root to discover research tasks (default: {DEFAULT_RESEARCH_TASKS_DIR}).",
    )
    p_research.add_argument(
        "--archive",
        type=Path,
        default=DEFAULT_RESEARCH_ATTEMPTS_PATH,
        help=f"Research-attempts archive (default: {DEFAULT_RESEARCH_ATTEMPTS_PATH}).",
    )
    p_research.add_argument(
        "--model-calls",
        type=Path,
        default=Path("runs/model_calls.jsonl"),
        help="Model-call audit ledger path (default: runs/model_calls.jsonl).",
    )
    p_research.add_argument(
        "--memory",
        type=Path,
        default=Path("runs/memory.jsonl"),
        help="Research-memory path (default: runs/memory.jsonl).",
    )
    p_research.set_defaults(func=_cmd_run_research)

    p_sumr = sub.add_parser(
        "summarize-research",
        help="Per-family summary of the research suite (Goal 09).",
    )
    p_sumr.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=DEFAULT_RESEARCH_ATTEMPTS_PATH,
        help=f"Research-attempts archive (default: {DEFAULT_RESEARCH_ATTEMPTS_PATH}).",
    )
    p_sumr.add_argument(
        "--model-calls",
        type=Path,
        default=Path("runs/model_calls.jsonl"),
        help="Model-call audit ledger, for per-family spend (default: runs/model_calls.jsonl).",
    )
    p_sumr.set_defaults(func=_cmd_summarize_research)

    p_sum = sub.add_parser("summarize-runs", help="Summarize an attempts archive.")
    p_sum.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path("runs/attempts.jsonl"),
        help="Path to attempts.jsonl (default: runs/attempts.jsonl).",
    )
    p_sum.set_defaults(func=_cmd_summarize_runs)

    p_meta = sub.add_parser(
        "propose-meta-change", help="Propose a bounded process change (Goal 05)."
    )
    p_meta.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path("runs/attempts.jsonl"),
        help="Path to attempts.jsonl (default: runs/attempts.jsonl).",
    )
    p_meta.add_argument(
        "--store",
        type=Path,
        default=Path("runs/meta_changes.jsonl"),
        help="Meta-change archive path, separate from attempts (default: runs/meta_changes.jsonl).",
    )
    p_meta.add_argument(
        "--benchmark",
        type=Path,
        nargs="+",
        default=[Path("tasks/code_improver/task_001")],
        help="Fixed benchmark task dir(s) for A/B validation.",
    )
    p_meta.add_argument(
        "-n",
        "--generations",
        type=int,
        default=3,
        help="Generations per benchmark run during A/B (default: 3).",
    )
    p_meta.add_argument(
        "--validate",
        action="store_true",
        help="Run A/B validation on the benchmark (needs the local model server).",
    )
    p_meta.set_defaults(func=_cmd_propose_meta_change)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
