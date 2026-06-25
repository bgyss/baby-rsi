# Goal Prompt 14 - Pricing Audit and Budget Calibration

## Goal

Make token pricing and budget estimates explicit, dated, configurable, and auditable. This
goal addresses the pricing-refinement items in `../14_project_retrospective.md` and
`../15_scale_cost_model.md`.

Budget gates are only useful if their cost estimates are close enough to current billing
reality. The system should not rely on stale baked-in prices when deciding whether to halt,
summarize spend, or plan a frontier pilot.

Depends on Goals 07, 08, 09, 10.

## Requirements

- Extend tier configs with optional per-model pricing overrides:
  - provider name,
  - model name,
  - input price per million tokens,
  - output price per million tokens,
  - cached-input price if supported,
  - last-reviewed date,
  - source URL or short source note.
- Update pricing resolution so config overrides take precedence over defaults and are logged
  in model-call audit metadata.
- Add a `siro pricing-audit` command that reports:
  - configured providers and models,
  - default price used or override price used,
  - missing prices,
  - stale review dates beyond a configurable threshold,
  - current run/day budget ceilings,
  - estimated cost for representative small/medium/heavy cycles.
- Add tests for:
  - override precedence,
  - missing-price warnings,
  - stale-review warnings,
  - cost estimation for known token counts,
  - local providers remaining zero-cost unless explicitly configured otherwise.
- Update `README.md` and `../15_scale_cost_model.md` with the command and the rule that
  scale decisions require a fresh pricing review.

## Acceptance criteria

- `siro pricing-audit --config config/tier1.frontier.yaml` prints one row per configured
  provider/model and exits nonzero for missing or stale prices when `--strict` is used.
- Model-call ledger rows include enough pricing metadata to reconstruct why a cost estimate
  was produced.
- Budget enforcement continues to halt and escalate on per-run, per-day, and per-call
  ceilings.
- Local Tier 0 runs remain free by default and do not require network or provider pricing.
- A docs-only pricing refresh can update config and docs without touching provider client
  code.

## Constraints

- Do not fetch pricing from provider websites at runtime. Network pricing refresh is a
  human-operated research task, not a control-plane model call.
- Do not let an agent widen budgets, alter pricing, or mark stale pricing as reviewed
  without human review.
- Do not weaken existing budget ceilings while adding better estimates.
- Treat provider billing dashboards as reconciliation sources; the local ledger remains an
  estimate.

## Self-improvement

This goal lets the loop reflect on spend with less ambiguity while preserving the budget
bounds in `../13_self_improvement_loop.md`.

- **Records**: pricing source metadata, model-call estimated costs, and audit warnings.
- **Reflects / proposes**: the outer loop may propose cheaper role-model bindings or budget
  changes based on cost-per-promotion, but budget changes become governance requests.
- **Validated / gated**: pricing changes pass tests, docs checks, and human review when they
  affect budget policy.
- **Bounds**: changing token/USD ceilings or treating stale pricing as current remains
  human-gated.
