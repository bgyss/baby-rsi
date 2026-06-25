# 16 - Low-Cost Local Validation Plan

This document gives a cheap validation ladder for `siro`: start with no model calls,
then move gradually toward local models and finally tightly capped frontier pilots.

The goal is to test the research organization without accidentally turning every
question into API spend.

## Principles

- Test control-plane invariants without models first.
- Use scripted clients for deterministic orchestration tests.
- Use Tier 0 local models before frontier models.
- Spend frontier tokens only after the benchmark and safety gates are already working.
- Promote only objective, reproducible improvements.
- Treat failed runs as useful data, not waste.

## Level 0 - Static and unit checks

Purpose:

- Verify the package imports.
- Exercise schemas, archives, gates, budget logic, governance, and provider parsing.
- Avoid model servers and network entirely.

Commands:

```zsh
UV_CACHE_DIR=.uv-cache uv run pytest tests/test_import.py -q
UV_CACHE_DIR=.uv-cache uv run pytest tests/test_archive.py tests/test_gates.py tests/test_budget.py -q
UV_CACHE_DIR=.uv-cache uv run pytest tests/test_governance.py tests/test_model_training.py -q
```

Expected cost:

- $0 API spend.

Good signal:

- Schema and gate changes do not regress basic invariants.

## Level 1 - Full scripted organization

Purpose:

- Run the multi-agent organization without real models.
- Exercise cross-model review by simulating distinct providers.
- Verify audit-ledger writes and escalation behavior.

Commands:

```zsh
UV_CACHE_DIR=.uv-cache uv run pytest tests/test_orchestrator.py -q
UV_CACHE_DIR=.uv-cache uv run pytest tests/test_research.py -q
UV_CACHE_DIR=.uv-cache uv run pytest tests/test_plane_isolation.py -q
```

Expected cost:

- $0 API spend.

Good signal:

- The control plane works even when model quality is replaced by deterministic fixtures.
- Safety disagreements escalate.
- Objective evaluators override model self-judgment.

## Level 2 - Full local test suite

Purpose:

- Catch integration failures across Goals 01-12.

Command:

```zsh
UV_CACHE_DIR=.uv-cache uv run pytest -q
```

Current known issue:

- The governed compute scale-up memory-breach test may fail on macOS because memory
  enforcement currently depends on controller-side RSS polling via `ps`.

How to interpret:

- A wall-clock breach failure is serious everywhere.
- A memory-breach failure on the portable local backend means the hard resource-control
  story is not production-ready yet.
- Before any real scale-up, run hard isolation tests in the target Linux/container
  environment.

Expected cost:

- $0 API spend.

## Level 3 - Tier 0 local CLI smoke

Purpose:

- Run real CLI paths with local/offline config.
- Verify archives, memory, and summaries from the user-facing interface.

Commands:

```zsh
UV_CACHE_DIR=.uv-cache uv run siro --help
UV_CACHE_DIR=.uv-cache uv run siro run-scaled tasks/research/training/tiny_mlp --compute-tier 0
UV_CACHE_DIR=.uv-cache uv run siro summarize-research runs/research_attempts.jsonl
```

Expected cost:

- $0 API spend.

Good signal:

- CLI defaults work.
- Tier 2 governed compute tier 0 runs without approval.
- Research attempts are archived and summarizable.

## Level 4 - Local model Tier 0

Purpose:

- Replace scripted clients with an actual local model while keeping the execution plane
  offline.

Start the local OpenAI-compatible model server:

```zsh
mise run serve-model
```

Run a single research task with the Tier 0 config:

```zsh
UV_CACHE_DIR=.uv-cache uv run siro run-research tasks/research/algorithm/pair_count \
  --config config/tier0.local.yaml \
  --objective "Improve the task against its objective metric."
```

Expected cost:

- $0 API spend.
- Local hardware/electricity only.

Good signal:

- The model server is reachable on the configured local endpoint.
- The same organization lifecycle works with local model calls.
- Attempts and model-call ledger entries are written.

Common failure modes:

- Local model server is not running.
- Served model name does not match config.
- Context is too long for the local model.
- Model output is not parseable JSON or does not contain an extractable code block.

## Level 5 - Frontier dry pilot

Purpose:

- Spend a very small amount to validate provider wiring, cross-provider safety review,
  and budget enforcement.

Before running:

- Set provider API keys in the control-plane environment only.
- Confirm `config/tier1.frontier.yaml` has a low `max_usd_per_run`.
- Prefer cheaper model bindings for the first smoke.
- Make sure the execution-plane sandbox still has no credentials.

Suggested budget:

```yaml
budget:
  max_usd_per_run: 0.25
  max_usd_per_day: 2.00
  max_tokens_per_call: 8000
```

Command:

```zsh
UV_CACHE_DIR=.uv-cache uv run siro run-research tasks/research/algorithm/pair_count \
  --config config/tier1.frontier.yaml \
  --objective "Improve count_pairs while preserving correctness."
```

Expected cost:

- Usually cents to a few dollars if the budget gates are configured correctly.

Good signal:

- Model calls are recorded in `runs/model_calls.jsonl`.
- Costs stay under configured ceilings.
- Safety review uses a different provider from implementation.
- A failed or escalated attempt is archived cleanly.

Stop conditions:

- Budget ceiling breach.
- Provider auth error.
- Provider rate-limit loop.
- Safety/gate disagreement.
- Any evidence that credentials or network access reached the execution plane.

## Level 6 - Small frontier A/B

Purpose:

- Measure whether frontier models outperform Tier 0 on objective metrics.

Plan:

1. Choose a fixed task list.
2. Run Tier 0 local model on all tasks.
3. Run cheap frontier mix on the same tasks.
4. Run strong frontier mix on the same tasks only if the cheap mix gives useful signal.
5. Compare cost per objective promotion.

Suggested run size:

- 10-30 cycles for an initial smoke.
- 50-100 cycles for a useful first comparison.
- More only after benchmark expansion.

Metrics to report:

- Total cycles.
- Total model spend.
- Passing attempts.
- Promoted attempts.
- Safety escalations.
- Hidden-test failures.
- Reproducibility failures.
- Cost per promoted attempt.

## Level 7 - Governed scale-up rehearsal

Purpose:

- Exercise the Tier 2 approval flow without expensive compute.

Run default tier:

```zsh
UV_CACHE_DIR=.uv-cache uv run siro run-scaled tasks/research/training/tiny_mlp \
  --compute-tier 0 \
  --experiment-id local-scale-rehearsal
```

Request a higher tier:

```zsh
UV_CACHE_DIR=.uv-cache uv run siro request-approval budget_increase \
  --target compute_tier:local-scale-rehearsal \
  --payload '{"compute_tier":1}' \
  --actor operator \
  --rationale "Rehearse governed scale-up after a passing tier 0 run."
```

List approvals:

```zsh
UV_CACHE_DIR=.uv-cache uv run siro list-approvals
```

Approve as a human operator:

```zsh
UV_CACHE_DIR=.uv-cache uv run siro approve <request_id> --by <human-id>
```

Run the governed tier:

```zsh
UV_CACHE_DIR=.uv-cache uv run siro run-scaled tasks/research/training/tiny_mlp \
  --compute-tier 1 \
  --experiment-id local-scale-rehearsal
```

Expected cost:

- $0 API spend if using the local/default task and no frontier model calls.

Good signal:

- Higher tier refuses without both a prior pass and approval.
- Approval is bound to the exact experiment/tier payload.
- Attempt and checkpoint records are written.

## What to automate first

Automate only after the manual loop is stable:

1. Full scripted test suite.
2. Docs consistency checks.
3. Pricing-review reminder.
4. Research summary generation.
5. Cost-per-promotion report.

Do not automate:

- Budget increases.
- Tier changes.
- Egress allowlist changes.
- Evaluator or safety-gate changes.
- Model deployment approvals.

Those remain human-gated by design.

## Minimal cheap pilot checklist

Before spending frontier tokens:

- `UV_CACHE_DIR=.uv-cache uv run pytest tests/test_orchestrator.py tests/test_research.py -q`
  passes.
- The known hard-resource-control status is understood.
- The benchmark task has a hidden/evaluator split.
- `config/tier1.frontier.yaml` has tight budget ceilings.
- Provider pricing has been reviewed and dated.
- `runs/model_calls.jsonl` is empty or intentionally carried forward.

After the pilot:

- Summarize research attempts.
- Reconcile ledger spend with provider dashboard spend.
- Record accepted, rejected, and escalated outcomes.
- Decide whether stronger models improve cost per promotion.
