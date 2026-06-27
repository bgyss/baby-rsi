# Goal Prompt 24 — Statistical Reproducibility Gate

## Goal

Generalize the reproducibility / promotion gate from **exact rerun agreement** to a **regime
spectrum**, so sciences whose evaluators are stochastic (numerical simulators, surrogate models,
docking scores) can promote on a sound statistical basis rather than being forced into bit-exact
determinism. This unlocks **Regime B — stochastic/in-silico**
(`../18_generalizing_to_sciences.md`) for every pack that follows, without relaxing the
invariant "no promotion on noise" — it is generalized, not weakened.

Today promotion requires near-bit-exact agreement (`REPRO_TOLERANCE = 1e-9` in `siro.research`,
`research_reproducibility_gate` / `research_improves`). This goal adds a third, noise-aware policy
selected by the pack/adapter's declared regime (Goal 22).

Depends on Goal 22 (the declared evaluator regime) and Goal 09 (the reproducibility gate it
generalizes). No new science is added here.

## Requirements

- **Three reproducibility policies**, selected by the adapter's declared regime:
  - `exact` — reruns must agree bit-for-bit (proof checkers, formal equivalence).
  - `seeded-deterministic` — today's behavior under `REPRO_TOLERANCE`.
  - `statistical` — promote only if the oriented gain over the incumbent clears a **confidence
    bound** across N seeded reruns; a lucky or noisy win cannot promote.
- **A typed statistical policy.** The `statistical` policy runs the evaluator N times under fixed,
  recorded seeds and computes a direction-aware confidence interval on the primary metric delta.
  Promotion requires the interval to exclude "no improvement" at a configured confidence level;
  N, the confidence level, and the seed set are **fixed harness parameters** (in the
  controller/config), never candidate-supplied.
- **Determinism of the test itself.** The seeds, N, and the resulting interval are recorded on
  the attempt so the *decision* is reproducible even though the metric is noisy. Re-running the
  gate on the same seeds yields the same promotion decision.
- **Secondary-metric regressions** are checked under the same policy (a noisy secondary may not
  regress past threshold within its confidence bound).
- **Default unchanged.** The ML pack and all existing tasks keep `seeded-deterministic`; nothing
  silently moves to `statistical`. A pack opts in by declaring the regime.
- **Document** the policy in `../05_evaluation_and_safety_gates.md`,
  `../18_generalizing_to_sciences.md`, the README status entry, and `../implementation_status.md`.

## Acceptance criteria

- `research_improves` / `research_reproducibility_gate` dispatch on the declared regime; the
  `exact` and `seeded-deterministic` paths reproduce existing behavior bit-for-bit (covered by
  tests).
- Under `statistical`, a candidate whose improvement is within noise (interval includes zero)
  does **not** promote, and a candidate whose improvement clears the confidence bound does
  (covered by tests with fixed seeds).
- The seeds, N, and computed interval are recorded on the attempt; re-running the gate on the
  same seeds yields the same decision.
- N, confidence level, and seed set are fixed harness/config parameters, unreachable by a
  candidate (covered by a test).
- `uv run siro check-docs` passes.

## Constraints

- **No promotion on noise.** The statistical policy is stricter, not looser: it must reject
  within-noise gains. It never replaces objective evaluation with model judgment.
- **Fixed, recorded parameters.** Seeds, replicate count, and confidence level live in the
  controller/config and are logged; a candidate cannot set or read them.
- **Plane isolation unchanged.** Replicates run in the existing offline sandbox under the same
  timeout and scrubbed env.
- **Human approval to widen.** Changing N, the confidence level, or the seed policy is a
  human-gated change reviewed like a meta-change.

## Self-improvement

This goal hardens the **validate** step of the bounded loop (`../13_self_improvement_loop.md`)
for noisy evaluators: improvement must clear a confidence bound, so the loop cannot promote on a
lucky draw.

- **Records**: replicate seeds and the computed interval on every attempt, so reflection can
  distinguish a real gain from variance; negatives included.
- **Reflects / proposes**: the meta-loop may propose changes to *which* candidates to try, but
  never to N / confidence / seeds (those are bounds).
- **Validated / gated**: the statistical gate is the authority for noisy packs; promotion needs a
  reproducible, bound-clearing improvement.
- **Bounds**: replicate count, confidence level, and seed set are human-gated; tightening is
  allowed by config, loosening is a reviewed escalation.
