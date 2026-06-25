# Research task — `sentiment_rules` (prompt/policy improvement)

## Objective

Improve the rule-based sentiment **policy** in `policy.py` so it labels more reviews
correctly. The policy is a function `classify(text)` that returns `1` for positive
sentiment and `0` for negative.

## Success metric

- **Primary:** `accuracy` — the aggregate pass rate over a held-out benchmark of labeled
  reviews (higher is better). The benchmark is controller-owned and never shown to you.
- **Precondition (`passed`):** `classify` must return a valid label (`0` or `1`) for every
  benchmark item without raising.

## Allowed edit surface

`policy.py` only. Keep the public signature `classify(text)`. A reasonable improvement
maintains lists of positive and negative cue words, counts cues, and handles simple
negation (e.g. "not good"). The baseline checks a single word and is easily beaten.

## Constraints

- Pure standard-library Python. No file/network/subprocess access (enforced by the static
  safety gate; the held-out benchmark never enters your prompt, so accuracy cannot come
  from leakage).
- The evaluator (`eval.py`) is read-only to you; promotion is decided by it, reproducibly.

Example inputs (illustrative only — **not** the benchmark):
`"this was a great movie"` → 1, `"terrible and boring"` → 0.
