"""``siro`` command-line interface.

The canonical interface to the system (``docs/10_repo_structure.md``); ``mise``
tasks are thin wrappers. Goal 01 ships the command *surface* the self-improvement
cycle uses:

- ``run-task``            — run the per-task improvement loop (Goal 02).
- ``summarize-runs``      — reflect on the archive (real: counts + pass rate + best).
- ``propose-meta-change`` — propose a process change (Goal 05).

Uses only the standard library ``argparse`` to keep Tier 0 dependency-light.
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from . import __version__
from .archive import JSONLArchive, ModelCallLedger
from .controller import Controller, select_best
from .memory import ResearchMemory, failure_signature
from .meta import MetaChangeStore, MetaResearcher
from .model_client import LocalOpenAIClient
from .schemas import MetaChangeRecord, MetaRecommendation


def _cmd_run_task(args: argparse.Namespace) -> int:
    model = LocalOpenAIClient()
    controller = Controller(
        archive=JSONLArchive(args.archive),
        ledger=ModelCallLedger(args.model_calls),
        memory=ResearchMemory(args.memory),
    )
    result = controller.run_task(args.task_dir, model=model, generations=args.generations)

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
    p_run.set_defaults(func=_cmd_run_task)

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
