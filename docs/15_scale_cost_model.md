# 15 - Deployment Scale and Cost Model

This document estimates what it would cost to run `siro` at increasing levels of
scale. The numbers are planning estimates, not purchase advice or billing truth.

Prices change. The figures below were checked against public provider pages on
2026-06-25 and should be refreshed before any budget decision.

## Sources checked

- OpenAI API pricing: https://openai.com/api/pricing/
- Anthropic Claude API pricing: https://platform.claude.com/docs/en/about-claude/pricing
- Runpod GPU pricing: https://www.runpod.io/pricing
- CoreWeave GPU pricing: https://www.coreweave.com/pricing

## What drives cost

The main cost drivers are:

1. Model-call volume: number of role calls per cycle.
2. Context size: prompt, retrieved memory, task files, and logs.
3. Output size: implementation patches, reviews, interpretations, and memory summaries.
4. Reruns: reproducibility checks and failed attempts.
5. Sandbox compute: wall-clock and memory budgets for candidate evaluation.
6. Storage and audit retention: ledgers, artifacts, checkpoints, traces.
7. Human review: Tier 2 governance approvals and incident review.

For the current Tier 1 organization, a typical research cycle can call these roles:

- Hypothesis
- Literature
- Implementation
- Evaluation narrative
- Safety review
- Interpretation
- Memory curator
- Meta-research proposal

In the default config, most reasoning roles bind to Anthropic and the safety role binds
to OpenAI. Evaluation itself remains objective and controller-owned; the model only
summarizes or reviews.

## Current public API pricing snapshot

Representative public token prices checked on 2026-06-25:

| Provider/model | Input per 1M tokens | Output per 1M tokens |
|---|---:|---:|
| Anthropic Claude Opus 4.8 | $5.00 | $25.00 |
| Anthropic Claude Sonnet 4.6 | $3.00 | $15.00 |
| Anthropic Claude Haiku 4.5 | $1.00 | $5.00 |
| OpenAI GPT-5.5 | $5.00 | $30.00 |
| OpenAI GPT-5.4 | $2.50 | $15.00 |
| OpenAI GPT-5.4 mini | $0.75 | $4.50 |

The code's internal default pricing table is only an estimate. Before any pilot, either
refresh that table or set explicit model price overrides in config.

## Per-cycle API cost estimates

The table below assumes six Anthropic Opus calls and one OpenAI GPT-5.4 safety call per
cycle. This is a conservative approximation of the current Tier 1 config shape. If the
cycle uses more roles, repeated retries, larger memory retrieval, or long code diffs,
actual cost rises.

| Cycle size | Tokens per paid call | Estimated cost per cycle |
|---|---:|---:|
| Small | 3k input / 1k output | about $0.26 |
| Medium | 10k input / 3k output | about $0.82 |
| Heavy | 50k input / 10k output | about $3.28 |

Approximate monthly API spend:

| Volume | Small cycles | Medium cycles | Heavy cycles |
|---:|---:|---:|---:|
| 100 cycles/day | about $780/mo | about $2,460/mo | about $9,840/mo |
| 1,000 cycles/day | about $7,800/mo | about $24,600/mo | about $98,400/mo |
| 10,000 cycles/day | about $78,000/mo | about $246,000/mo | about $984,000/mo |

These figures exclude human review, storage, observability, CI, and sandbox compute.

## Cheaper API configurations

A cheaper pilot can change provider bindings without changing code:

- Use Sonnet for most reasoning roles and reserve Opus for implementation.
- Use Haiku or mini models for memory curation, triage, and summarization.
- Keep safety review cross-provider but choose the cheapest model that still catches
  the relevant failure modes.
- Limit retrieved memory and file context aggressively.
- Use batch or flex processing where latency does not matter.

Cost-control rule of thumb:

- Use strong models for proposal and implementation.
- Use cheaper models for summarization and agenda maintenance.
- Use objective code for evaluation whenever possible.
- Spend on reruns only for promotion contenders.

## Local and rented GPU cost estimates

Local or rented GPU inference can reduce token spend, but it adds operational work:
model serving, queueing, monitoring, model quality evaluation, hardware availability,
and security updates.

Representative public GPU prices checked on 2026-06-25:

| Provider | Hardware | Public price signal | 24/7 monthly equivalent |
|---|---|---:|---:|
| Runpod | L40S 48GB | about $0.99/hr | about $723/mo |
| Runpod | A100 SXM 80GB | about $1.49/hr | about $1,088/mo |
| Runpod | H100 class | about $4.18/hr in listed single-GPU bands | about $3,051/mo |
| CoreWeave | 8x HGX H100 | about $49.24/hr | about $35,945/mo |
| CoreWeave | 8x HGX H200 | about $50.44/hr | about $36,821/mo |

These prices do not include all possible storage, networking, reserved-capacity, support,
or data-transfer charges. They are useful for order-of-magnitude planning.

## Deployment tiers

### Local developer tier

Purpose:

- Verify invariants.
- Run scripted-client tests.
- Run Tier 0 local-model experiments.
- Expand benchmark tasks.

Likely cost:

- $0 API spend.
- Electricity and local hardware only.
- Optional local GPU or external model server.

Good for:

- Daily development.
- Safety regression testing.
- Benchmark authoring.
- Meta-research logic tests.

Not good for:

- Measuring frontier-model research performance.
- Production reliability.
- Hard multi-tenant isolation.

### Cheap frontier pilot

Purpose:

- Determine whether frontier calls improve benchmark outcomes over Tier 0.
- Measure cost per accepted promotion.
- Tune role-model assignments.

Likely cost:

- $100-$1,000 for a useful early pilot if budgets are kept tight.
- Run 50-300 cycles across the benchmark suite.
- Cap per-run and per-day spend in config.

Good for:

- Cost-per-promotion measurement.
- Role ablation tests.
- Provider/model comparison.

Not good for:

- Autonomous scale-up.
- Large training experiments.
- Production service promises.

### Single-worker production pilot

Purpose:

- Run a controlled research queue with real audit logs and human governance.

Likely cost:

- API mode: low thousands to tens of thousands per month, depending on cycle volume.
- GPU mode: roughly $700-$3,000 per month for a single always-on rented GPU, plus
  storage and operations.

Required refinements:

- Durable database for ledgers.
- Better observability.
- Harder sandbox backend.
- Pricing audit.
- Governance identity.

### Multi-worker scale-up

Purpose:

- Run many experiments in parallel.
- Support multiple task families and longer research queues.

Likely cost:

- API mode: tens of thousands to hundreds of thousands per month.
- GPU mode: dedicated multi-GPU clusters can reach tens of thousands per month before
  staffing and platform costs.

Required refinements:

- Queueing system.
- Worker isolation.
- Database-backed run coordination.
- Policy-based budget allocation.
- Centralized artifact store.
- Per-tenant or per-project cost accounting.

### Governed training scale-up

Purpose:

- Run approved model-training experiments under Tier 2 controls.

Likely cost:

- Toy deterministic training: nearly free locally.
- Small fine-tunes: usually single-GPU or API fine-tuning cost scale.
- Serious model training: quickly becomes cluster-scale and should be treated as a
  separate governed program, not an automatic extension of the agent loop.

Required refinements:

- Training-data governance.
- Artifact signing.
- Reproducible training environment.
- Deployment review board.
- Strict separation between training, evaluation, and deployment approval.

## Recommended budget controls

Add these controls before frontier or scale-up pilots:

- Config-level model price overrides with reviewed dates.
- Per-role token ceilings.
- Per-cycle total token ceilings.
- Per-task-family budget pools.
- Daily hard stop and email/chat alert.
- Provider dashboard reconciliation against `runs/model_calls.jsonl`.
- A command that reports cost per promoted attempt, not just total spend.
- A "dry run" mode that estimates spend from prompt sizes before making calls.

## Key metric: cost per promotion

The most useful financial metric is not cost per cycle. It is:

```text
cost per accepted, reproducible, safety-passing promotion
```

Track it by task family and model configuration:

- Total cycles.
- Total API spend.
- Passing attempts.
- Promoted attempts.
- Safety escalations.
- Hidden-test failures.
- Reproducibility failures.
- Cost per promotion.

If a stronger model doubles per-cycle cost but quadruples promotion rate, it may be
cheaper in practice. If it mostly produces better narratives without objective wins, it
is not buying research progress.

## Recommended first financial experiment

Run this before any scale-up decision:

1. Expand the benchmark suite enough to avoid one-task overfitting.
2. Run the same benchmark with:
   - Tier 0 local model.
   - Cheap frontier mix.
   - Strong frontier mix.
3. Use identical task order and budget ceilings.
4. Summarize:
   - total spend,
   - win rate,
   - promotion rate,
   - safety escalation rate,
   - cost per promotion,
   - common failure signatures.

Exit criterion:

```text
Frontier spend is justified only if it produces materially more objective,
reproducible, safety-passing promotions than Tier 0 for the same benchmark.
```
