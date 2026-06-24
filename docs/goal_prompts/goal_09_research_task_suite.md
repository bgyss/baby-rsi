# Goal Prompt 09 — Research-Shaped Task Suite and Evaluation Harness

## Goal

Give the Tier 1 organization real work: a suite of research-shaped tasks (beyond single-function code repair) with objective evaluators, so the frontier agents can be measured doing genuine research rather than templated mutation.

Depends on Goal 08.

## Requirements

Create `tasks/research/` task directories, each with:

```text
brief.md          # objective, constraints, allowed edit surfaces, success metric
baseline/         # starting code/config the org improves on
eval.py           # objective, reproducible evaluator (the authority for promotion)
hidden/           # optional held-out tests/data, never shown to agents
```

Seed at least three task families with stable, objective metrics, for example:

- Algorithm/implementation improvement scored by correctness + runtime/memory.
- A Karpathy-style tiny-training task (extends Goal 06) scored by validation loss / bits-per-byte under a fixed wall-clock budget.
- A prompt- or policy-improvement task scored by aggregate pass rate over a benchmark set.

## Evaluation harness

- Each `eval.py` returns a typed metric record (primary + secondary) consumed by the existing evaluator and promotion gate.
- Hidden tests/data live outside the task directory and are never placed in any model prompt.
- Results must be reproducible across reruns before promotion.

## Acceptance criteria

- The Tier 1 org runs a full lifecycle on each task family and writes structured memory entries (successes and negative results).
- Promotion is decided by the objective evaluator, not model self-judgment.
- Metric gains cannot come from altered validation data or hidden-test leakage (enforced, not assumed).
- A summary command reports, per task family: pass rate, median cycles to success, safety-gate failures, token/USD spend, and strategy diversity.

## Constraints

- No network or package installation in the execution plane.
- Evaluators are read-only to agents; editing one requires human approval.
- Expanding benchmark scope or compute/token budget requires human approval.

## Self-improvement

This goal provides the **fixed benchmark the validate step depends on** (`../13_self_improvement_loop.md`): a suite of genuine research-shaped tasks with objective evaluators, so improvement is measured on real work rather than templated mutation.

- **Records**: per-task results across the suite, so the loops can reflect on aggregate progress, not a single task.
- **Reflects / proposes**: the suite is the held-fixed A/B set both loops compare candidates and meta-changes against.
- **Validated / gated**: evaluators must reward genuine task success, not visible-test overfitting or loopholes — a guard the self-improvement gate relies on.
- **Bounds**: per `../13_self_improvement_loop.md` — expanding benchmark scope or compute/token budget requires human approval.
