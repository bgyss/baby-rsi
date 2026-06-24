# 02 — Research Operating Model

## Research work item types

| Work item | Description | Example |
|---|---|---|
| Hypothesis | A falsifiable research idea | "Changing optimizer schedule improves validation loss under fixed budget." |
| Experiment | A concrete test of a hypothesis | Run baseline vs modified schedule for 5 minutes. |
| Evaluation | Measurement of experiment outputs | Compare validation loss, runtime, memory, failures. |
| Interpretation | Explanation of result and next action | "Improvement only appears at low batch size; retest." |
| Meta-change | Change to the research process itself | Modify prompt used by Hypothesis Agent. |

## Work item lifecycle

```text
proposed
→ triaged
→ planned
→ implemented
→ running
→ evaluated
→ interpreted
→ promoted | rejected | needs_followup
→ archived
```

## Research cadence

### Local testbed cadence

- Run many small experiments.
- Prefer 1–10 minute runs.
- Use deterministic tasks when possible.
- Maintain a baseline archive.

### Lab-scale cadence

- Promote only ideas that survive repeated small-scale validation.
- Use budget tiers.
- Require human review before major compute allocation.

## Decision rights

| Decision | Agent can decide? | Human required? |
|---|---:|---:|
| Generate hypothesis | Yes | No |
| Run small sandboxed test | Yes | No |
| Promote to medium experiment | Maybe | Configurable |
| Modify evaluator | No | Yes |
| Modify safety policy | No | Yes |
| Raise deployment tier (e.g. 0 → 1) | No | Yes |
| Add a network egress endpoint | No | Yes |
| Raise token / USD budget ceiling | No | Yes |
| Launch large training run | No | Yes |
| Release model/artifact | No | Yes |

Lowering the tier (1 → 0) is always safe and config-only.

## Budget tiers

```text
Tier 0: static checks only
Tier 1: local unit tests and microbenchmarks
Tier 2: short training/eval run
Tier 3: repeated ablations
Tier 4: larger confirmation run
Tier 5: production-scale training or deployment candidate
```

These are **compute** budget tiers (per experiment). They are orthogonal to the **deployment tiers** (Tier 0 local / Tier 1 frontier / Tier 2 governed scale-up) in `07_model_providers_and_tiers.md`, which govern which model providers and network access the whole system may use. When frontier providers are active, token / USD spend is budgeted alongside compute and is subject to per-run and per-day ceilings.

## Promotion rule template

A work item may advance if:

1. It beats the baseline on the primary metric.
2. It does not regress on required secondary metrics.
3. It passes safety checks.
4. It is reproducible.
5. It has a clear interpretation.
6. It has not modified forbidden surfaces.
