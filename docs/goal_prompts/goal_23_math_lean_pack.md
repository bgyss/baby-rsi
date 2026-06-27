# Goal Prompt 23 — Mathematics Proof-Search Pack (Lean)

## Goal

Ship the **first non-ML domain pack**: a mathematics pack whose evaluator is a formal proof
checker (Lean via `lake build`). A candidate is a proof term or construction for a fixed theorem
statement; the evaluator runs the checker offline and emits pass/fail plus secondary metrics
(proof length, dependency count). This is **Regime A — formal/exact**
(`../18_generalizing_to_sciences.md`): fully deterministic, offline, reproducible bit-for-bit,
and therefore the cleanest possible proof that the Goal 22 pack interface generalizes beyond
software — it stresses the pack interface and nothing else (no new gate, no governance).

Depends on Goal 22 (the domain-pack interface and `EvaluatorAdapter`) and Goal 09 (the research
task shape it reuses).

## Requirements

- **A `packs/math/` pack** conforming to the Goal 22 layout, declaring evaluator regime `exact`.
- **A Lean evaluator adapter.** `evaluator.py` runs the proof checker on the candidate against a
  fixed, controller-owned theorem statement, in the offline execution plane, under a hard
  timeout. It emits a `MetricRecord`: primary = proof verified (boolean → pass), secondary =
  proof length / step count and axiom/dependency count (lower is better), with the correct
  `higher_is_better` direction. The theorem statement and any held-out check live outside the
  candidate's working copy (controller-owned, `SIRO_HIDDEN_PATH`), so a candidate cannot weaken
  what it is proving.
- **Seed task families** with stable, objective metrics — at minimum: prove a fixed lemma
  (correctness only), and improve an existing valid proof (shorter / fewer dependencies while
  still verifying). Each task ships `task.json`, an agent-visible `brief.md`, a `baseline/` edit
  surface, and held-out checks where applicable.
- **The toolchain is offline and pinned.** The Lean toolchain is provisioned by the dev
  environment (nix/mise), never installed by the loop; the execution plane has no network and may
  not fetch a mathlib or any dependency at eval time — required libraries are vendored/pinned.
- **Role-prompt specialization.** `prompts/` adapts the Implementation and Literature roles to
  mathematics (state the goal, cite lemmas from the pinned corpus), with the default org roles
  and lifecycle otherwise unchanged.
- **Document the pack** in `../18_generalizing_to_sciences.md`, the README status entry, and
  `../implementation_status.md`.

## Acceptance criteria

- The Tier 1 org runs a full lifecycle on each math task family and writes structured memory
  entries (verified proofs and negative results).
- Promotion is decided by the proof checker, not model self-judgment: an unverified proof never
  promotes, and a candidate that edits the theorem statement to make it trivial fails the
  edit-surface / held-out check.
- Results are reproducible bit-for-bit across reruns (regime `exact`).
- The pack runs at Tier 0 and Tier 1 by config only, with no code change to the core loop.
- `uv run siro check-docs` passes.

## Constraints

- **No network or package installation in the execution plane.** The proof checker runs offline
  against a pinned toolchain and a vendored library snapshot; no eval-time fetch.
- **The theorem statement is read-only to agents.** A candidate may supply a proof but never
  rewrite the statement, the checker invocation, or the held-out check.
- **Config-only selection.** Selecting the math pack or its tier is config, never code.
- **No bound moves.** The pack inherits the existing gates, budgets, and sandbox unchanged; it may
  narrow its toolset but never widen it.

## Self-improvement

This goal extends the bounded loop (`../13_self_improvement_loop.md`) to a formal-mathematics
domain without moving any bound: the same observe → reflect → propose → validate → gate → record
cycle, with a proof checker as the objective evaluator.

- **Records**: every proof attempt, verified or not, with its length/dependency metrics and a
  failure signature; negatives are first-class (a failed proof search is data).
- **Reflects / proposes**: the meta-loop may propose math-pack-local prompt or selection
  heuristics (e.g. which lemmas to retrieve first), reviewed like any meta-change.
- **Validated / gated**: the proof checker is the authority; a proof promotes only if it verifies
  and improves the declared secondary metric without weakening the statement.
- **Bounds**: expanding the theorem set, the vendored library snapshot, or the budget is a
  human-gated change; the checker and statements are read-only to agents.
