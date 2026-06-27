# Goal Prompt 17 - Research Benchmark Suite Expansion

## Goal

Expand the fixed research benchmark suite enough to measure real improvement and resist
overfitting. This goal addresses the benchmark refinement in `../14_project_retrospective.md`
and is the main prerequisite for meaningful cost-per-promotion measurements.

The current suite proves the lifecycle across a few task families. This goal turns it into
a broader benchmark set for evaluating Tier 0, Tier 1, and meta-research changes.

Depends on Goals 04, 05, 09, 14.

## Requirements

- Expand `packs/ml/tasks/` to at least 10 tasks per existing family:
  - algorithm,
  - training,
  - policy.
- Add at least two new families that exercise different research behavior, such as:
  - data-cleaning transformations,
  - parser/validator repair,
  - retrieval/ranking heuristics,
  - test-generation under fixed evaluators.
- For each task, include:
  - `task.json`,
  - `brief.md`,
  - `baseline/`,
  - controller-owned `eval.py`,
  - optional `hidden/` held-out data.
- Add adversarial task variants:
  - visible tests that are incomplete,
  - evaluator-loophole temptations,
  - hidden data leakage temptations,
  - primary metric wins that regress secondary metrics,
  - noisy metrics requiring repeated measurement.
- Extend `summarize-research` to report:
  - accepted/promoted/mixed/failed outcomes by family,
  - median cycles to success,
  - safety-gate failures,
  - hidden-test failures,
  - reproducibility failures,
  - token/USD spend,
  - strategy diversity,
  - cost per promotion when model-call data is available.

## Acceptance criteria

- The suite discovers at least the required number of tasks and families.
- Every task can run its baseline through the sandbox and produce a typed metric.
- Known-good candidates exist for a representative subset and demonstrate improvements.
- Hidden data is never included in prompts or candidate working directories.
- A fast-but-wrong candidate cannot promote.
- A candidate that reads hidden-path environment variables is blocked before execution.
- `summarize-research` produces meaningful per-family results across the expanded suite.

## Constraints

- Keep evaluators controller-owned and read-only to agents.
- Do not make tasks depend on network access or autonomous package installation.
- Keep task runtime small enough for cheap local testing by default.
- Do not change promotion rules to make the larger suite look better.
- Do not expose hidden benchmarks through prompts, memory summaries, or docs.

## Self-improvement

This goal strengthens the fixed benchmark used by the validation step of
`../13_self_improvement_loop.md`.

- **Records**: every benchmark attempt, including failed, adversarial, and noisy cases.
- **Reflects / proposes**: the outer loop can identify strategy failures by family and
  propose bounded process changes.
- **Validated / gated**: candidate and meta-change promotion must improve the expanded fixed
  suite reproducibly without safety or secondary-metric regressions.
- **Bounds**: adding or changing benchmark evaluators, hidden data, or scoring policy is a
  human-reviewed benchmark change, not an autonomous self-improvement.
