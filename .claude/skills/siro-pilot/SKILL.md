---
name: siro-pilot
description: Run the bounded operational pilot (Goal 20) end-to-end and interpret its cost-per-promotion report. Use when the user wants to compare Tier 0 / cheap-frontier / strong-frontier arms on the fixed task list, estimate cost per promotion, or get a continue/revise/stop recommendation before any scale-up.
---

# Run the siro operational pilot

A fixed, budget-capped comparison of three arms (Tier 0 local, cheap frontier, strong
frontier) on an immutable task list, ending in a Markdown cost-per-promotion report with a
continue/revise/stop recommendation. The pilot **approves no scale-up by itself** — it only
produces evidence for a human decision.

## The three steps (run in order)

```zsh
uv run siro pilot-init                       # write the fixed plan + command transcript
uv run siro pilot-run                        # run the required arms into per-arm archives
uv run siro pilot-report                     # render the cost-per-promotion report
```

- `pilot-init` is reproducible and writes the plan under the pilot root; the task list and
  per-arm configs are fixed — do not edit them to flatter a result.
- `pilot-run` runs the **required** arms (Tier 0 + cheap frontier). Add
  `--include-conditional` to also run the strong-frontier follow-up; run a single arm with
  `--arm <name>` (e.g. `tier0_local`, `tier1_cheap_frontier`).
- `pilot-report` renders from the archived research attempts + model-call ledgers to
  `reports/`; pass `--provider-reconciliation "<note/url>"` if you have dashboard figures
  to cross-check estimated spend against.

The frontier arms make real provider calls and cost money. Before running them, confirm the
user wants to spend, and that any budget headroom they need is already approved (see
**/siro-govern**). The Tier 0 arm is free and safe to run unprompted.

## Interpret the report

Read the rendered report and relay, concisely:

- **Outcomes per arm**: accepted/promoted vs mixed/escalated vs failed.
- **Cost**: estimated spend, cost per accepted promotion, cost per family.
- **Integrity rates**: hidden-test / reproducibility / safety rates.
- **Flags**: any budget breach or missing evidence the report calls out.
- **Recommendation**: the report's continue/revise/stop verdict — present it as the
  report's recommendation, and make clear that acting on it (a real scale-up) is a separate
  human-gated governance step, not something this pilot or you authorize.

Surface the file the report was written to so the user can open it.
