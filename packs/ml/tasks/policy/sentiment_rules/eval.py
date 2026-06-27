"""Objective, reproducible evaluator for the `sentiment_rules` research task (Goal 09).

Controller-owned: copied into the offline sandbox, never candidate-supplied. It imports
the candidate's `classify` and scores it over the **held-out** benchmark in `_hidden.json`
(never shown to the model). The primary metric is aggregate accuracy (higher is better);
`passed` requires a valid label for every item. Deterministic — the benchmark is fixed —
so the reproducibility gate sees an identical accuracy on rerun. Prints one JSON record.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def main() -> int:
    try:
        import policy  # noqa: PLC0415 - candidate edit surface
    except Exception as exc:  # pragma: no cover
        print(json.dumps({"error": f"could not import policy.py: {exc}"}))
        return 0

    # Held-out benchmark lives outside the candidate's cwd; its path is given via env var.
    benchmark = json.loads(Path(os.environ["SIRO_HIDDEN_PATH"]).read_text(encoding="utf-8"))["benchmark"]
    correct = 0
    for item in benchmark:
        try:
            label = policy.classify(item["text"])
        except Exception as exc:
            print(json.dumps({"primary": 0.0, "passed": False, "notes": f"classify raised: {exc}"}))
            return 0
        if label not in (0, 1):
            print(
                json.dumps(
                    {"primary": 0.0, "passed": False, "notes": f"classify returned non-label {label!r}"}
                )
            )
            return 0
        if label == item["label"]:
            correct += 1

    total = len(benchmark)
    accuracy = correct / total if total else 0.0
    print(
        json.dumps(
            {
                "primary": round(accuracy, 9),
                "passed": True,
                "secondary": {"correct": float(correct), "total": float(total)},
                "notes": "aggregate pass rate over the held-out benchmark",
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
