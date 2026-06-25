# Goal Prompt 20 - Bounded Operational Pilot and Cost-per-Promotion Report

## Goal

Run a bounded Tier 1 operational pilot and produce a decision-quality report on whether
frontier spend buys measurable research progress over Tier 0. This goal captures the
"Operational pilot" milestone from `../14_project_retrospective.md` and the financial
experiment recommended in `../15_scale_cost_model.md`.

This is not a scale-up goal. It is a measurement goal: run a fixed, budget-capped benchmark
comparison and report cost, promotion quality, safety escalations, and failure modes.

Depends on Goals 13, 14, 17, 18. Goal 15 should be complete before using governed compute
tiers above the local default.

## Requirements

- Define a fixed pilot plan under `docs/` or `runs/pilots/`:
  - benchmark task list,
  - model/provider configurations,
  - per-run and per-day budget ceilings,
  - random seeds or deterministic ordering,
  - stop conditions,
  - expected report path.
- Run the same benchmark set under at least:
  - Tier 0 local model,
  - cheap frontier mix,
  - strong frontier mix if the cheap frontier run gives useful signal.
- Preserve strict budget ceilings:
  - no budget widening during the pilot,
  - no execution-plane network,
  - no autonomous package install,
  - no evaluator or safety-gate changes.
- Produce a pilot report that includes:
  - total cycles,
  - total estimated spend,
  - provider-dashboard reconciliation if available,
  - pass rate,
  - promotion rate,
  - hidden-test failure rate,
  - reproducibility failure rate,
  - safety escalation rate,
  - cost per accepted promotion,
  - cost per family,
  - common failure signatures,
  - recommendation: continue, revise, or stop.
- Archive the exact configs, command transcript summary, and attempt/model-call ledgers used
  for the report.

## Acceptance criteria

- The pilot can be run with a strict maximum spend cap and halts on budget breach.
- Tier 0, cheap frontier, and strong frontier results are comparable because they use the
  same task set and promotion rules.
- The report separates accepted/promoted, mixed/escalated, and failed results.
- Cost per promotion is computed from the model-call ledger and clearly labeled as an
  estimate.
- The report states whether frontier spend produced materially more objective,
  reproducible, safety-passing promotions than Tier 0.
- No scale-up recommendation is made without the benchmark, budget, and safety evidence.

## Constraints

- Do not change benchmark evaluators, hidden data, gates, budgets, or provider bindings
  mid-pilot unless the run is stopped and a new pilot plan is created.
- Do not treat model-written narratives as success evidence without objective metrics.
- Do not exceed configured budgets; a budget breach is a halt-and-escalate event.
- Do not run governed compute tiers above the local default unless the hard resource
  isolation backend is ready for the target environment.

## Self-improvement

This goal measures whether the self-improvement loop is actually buying progress. It turns
cost, promotion quality, and safety escalation into feedback for the bounded cycle in
`../13_self_improvement_loop.md`.

- **Records**: pilot plan, configs, attempts, model-call ledger, summaries, and final report.
- **Reflects / proposes**: the report may propose role-model rebinding, benchmark expansion,
  or process changes based on observed cost-per-promotion.
- **Validated / gated**: any proposed process or budget change from the pilot still goes
  through the normal objective validation and governance gates.
- **Bounds**: the pilot may recommend scale-up but may not approve it; budget expansion,
  tier changes, and deployment changes remain human-gated.
