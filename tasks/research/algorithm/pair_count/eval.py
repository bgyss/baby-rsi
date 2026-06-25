"""Objective, reproducible evaluator for the `pair_count` research task (Goal 09).

This file is **controller-owned**: it is copied into the offline sandbox by the
controller, never supplied by a candidate, so a candidate cannot rewrite what scores it.
It imports the candidate's `solution.py`, then:

1. checks correctness on the held-out cases in `_hidden.json` (never shown to the model);
2. checks correctness on a fixed, deterministic performance workload against an independent
   brute-force reference (so a fast-but-wrong candidate cannot win);
3. measures `executed_lines` — the number of source lines `solution.py` executes on that
   workload, via `sys.settrace` — as the deterministic primary metric (lower is better; a
   reproducible proxy for runtime that does not depend on wall-clock noise).

It prints a single JSON metric record on its last stdout line.
"""

from __future__ import annotations

import json
import os
import random
import sys
from pathlib import Path


def _load_hidden():
    """Read the held-out data from the controller-provided path (outside the candidate cwd)."""
    return json.loads(Path(os.environ["SIRO_HIDDEN_PATH"]).read_text(encoding="utf-8"))


def _reference_count(nums, target):
    """Independent brute-force ground truth (kept separate from the candidate)."""
    count = 0
    for i in range(len(nums)):
        for j in range(i + 1, len(nums)):
            if nums[i] + nums[j] == target:
                count += 1
    return count


def _perf_workload():
    """A fixed, deterministic workload used only to measure executed lines."""
    rng = random.Random(20240624)
    nums = [rng.randint(0, 40) for _ in range(140)]
    target = 41
    return nums, target


def _count_executed_lines(fn, solution_file, *args):
    """Run ``fn(*args)`` and count line events inside ``solution_file`` (deterministic)."""
    target_name = Path(solution_file).resolve()
    counter = {"lines": 0}

    def tracer(frame, event, _arg):
        if event == "line" and Path(frame.f_code.co_filename).resolve() == target_name:
            counter["lines"] += 1
        return tracer

    sys.settrace(tracer)
    try:
        result = fn(*args)
    finally:
        sys.settrace(None)
    return result, counter["lines"]


def main() -> int:
    try:
        import solution  # noqa: PLC0415 - candidate edit surface, imported at eval time
    except Exception as exc:  # pragma: no cover - import failure is a candidate error
        print(json.dumps({"error": f"could not import solution.py: {exc}"}))
        return 0

    cases = _load_hidden()["cases"]

    # 1. Correctness on the held-out cases.
    correct = 0
    for case in cases:
        try:
            got = solution.count_pairs(list(case["nums"]), case["target"])
        except Exception as exc:
            print(json.dumps({"primary": 0.0, "passed": False, "notes": f"raised on hidden case: {exc}"}))
            return 0
        if got == case["expected"]:
            correct += 1
    cases_passed = correct == len(cases)

    # 2. Correctness on the performance workload vs an independent reference.
    nums, tgt = _perf_workload()
    reference = _reference_count(nums, tgt)
    try:
        got, executed = _count_executed_lines(solution.count_pairs, solution.__file__, list(nums), tgt)
    except Exception as exc:
        print(json.dumps({"primary": 0.0, "passed": False, "notes": f"raised on workload: {exc}"}))
        return 0
    workload_correct = got == reference
    passed = cases_passed and workload_correct

    print(
        json.dumps(
            {
                "primary": float(executed),
                "passed": passed,
                "secondary": {
                    "hidden_cases_correct": float(correct),
                    "hidden_cases_total": float(len(cases)),
                    "workload_result": float(got),
                    "reference_result": float(reference),
                },
                "notes": "executed_lines on the fixed workload (lower is better)",
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
