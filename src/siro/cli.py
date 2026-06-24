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
from .model_client import LocalOpenAIClient


def _cmd_run_task(args: argparse.Namespace) -> int:
    model = LocalOpenAIClient()
    controller = Controller(
        archive=JSONLArchive(args.archive),
        ledger=ModelCallLedger(args.model_calls),
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
    return 0


def _cmd_propose_meta_change(args: argparse.Namespace) -> int:
    archive = JSONLArchive(args.path)
    n = len(archive.read_all())
    print(f"propose-meta-change: read {n} attempt(s) from {args.path}")
    print("Not yet implemented — the bounded meta-research loop lands in Goal 05.")
    print("Reminder: meta-changes are proposals only; promotion is human-gated.")
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
    p_meta.set_defaults(func=_cmd_propose_meta_change)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
