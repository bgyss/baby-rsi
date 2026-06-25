# Goal Prompt 11 — Governed Compute Scale-Up (longer experiments, larger budgets)

## Goal

Allow **larger compute and longer-running experiments** under explicit governance — the
"larger compute, longer experiments" part of Tier 2 (`../07_model_providers_and_tiers.md`) —
without weakening plane isolation or the promotion gates. A bigger budget is earned by
passing smaller-budget gates first and unlocked only by a human-approved governance request;
it is never a code change and never opens the execution plane to the network.

Depends on Goals 06, 08, 10.

## Requirements

- Extend `src/siro/budget.py` with **compute budget tiers** (`../02_research_operating_model.md`):
  per-experiment ceilings on wall-clock, memory, and (optionally) CPU/process count, enforced
  by the controller. The default tier needs no approval; any tier above the configured
  threshold requires a matching Goal 10 governance approval before the run starts.
- **Promotion-before-budget allocation** (`../00_principles.md` principle 3): an experiment
  may only request a larger compute tier after it has passed the gates at a smaller tier. The
  lineage (small-budget result → larger-budget request) is recorded; "speculative hypothesis
  → expensive run" in one jump is refused.
- **Checkpointing + resumability** for long runs, so a halt-and-escalate (budget breach or
  governance denial) does not lose or corrupt work, and the run stays seeded and replayable.
- Hard resource ceilings: subprocess timeouts and a memory cap enforced on the execution
  plane; a breach halts and escalates, leaving the archive consistent.
- CLI: a way to run a governed, scaled experiment (e.g. a `--compute-tier` flag on the run
  commands, or `run-scaled`) that consults the governance gate for tiers above the threshold.

## Acceptance criteria

- A compute tier above the default is **refused** unless a matching governance approval
  (Goal 10) exists; the refusal is recorded as a pending escalation (assert in tests).
- Wall-clock and memory ceilings are enforced; a breach halts and escalates **without
  corrupting the archive**, and a checkpoint allows the run to resume.
- An experiment cannot reach a large budget without first passing the small-budget gates;
  the budget-escalation lineage is recorded.
- **Plane isolation holds unchanged at scale** (assert in `tests/test_plane_isolation.py`):
  no network, no credentials, hard timeouts — larger compute never means cloud egress,
  autonomous install, or a model client in the execution plane.
- Compute tier is config + approval, never code; lowering it is always safe.

## Constraints

- Reuse the existing lifecycle, gates, evaluator, and memory unchanged; scale-up is a budget
  and governance concern, not a loop redesign.
- Budgets expand **only** via human approval (Goal 10); no cloud compute and no
  execution-plane network, ever; every escalation is audited.
- Objective evaluators still decide promotion; results must stay reproducible across reruns.

## Self-improvement

This goal lets both loops operate at a larger scale while keeping the cycle and bounds of
`../13_self_improvement_loop.md` intact.

- **Records**: every scaled-experiment attempt and outcome (including negatives, budget
  breaches, and governance denials) to the archive and memory.
- **Reflects / proposes**: the loops may propose a larger-budget experiment; it becomes a
  governance request, validated on the same fixed benchmark before any promotion.
- **Validated / gated**: objective evaluators score first; promotion still requires a
  reproducible improvement that clears the gates — a larger budget never buys a looser gate.
- **Bounds**: per `../13_self_improvement_loop.md` — expanding compute/token/USD budgets is
  human-gated, now enforced through Goal 10's governance gate.
