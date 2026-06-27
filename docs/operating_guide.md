# Operating Guide

Reference for `uv run siro ...`. Use repo-local host skills for dialogue-driven operation —
[`.claude/skills/`](../.claude/skills/) (Claude Code slash commands) and
[`.codex/skills/`](../.codex/skills/) (Codex skills with the same workflow names) — and use <!-- docs-privacy-allow -->
this file for exact commands and flags.

## Rules

- Tiers are config: Tier 0 local/offline, Tier 1 frontier providers, Tier 2 governed.
- Candidate code runs only in the execution plane: offline, temp-dir based, timed, and
  credential-free.
- Agents propose; humans approve governed actions.
- Promotion requires metric improvement, safety, reproducibility, and edit-surface compliance.

## Setup

```zsh
nix develop
mise install
mise run sync
mise run test
```

## Global Flags

```zsh
uv run siro --json summarize-research
uv run siro --dry-run run-scaled --compute-tier 1
uv run siro <command> --help
```

| Flag | Effect |
|---|---|
| `--json` | Machine-readable output for read-only summaries. |
| `--dry-run` | Print command, tier, and governance impact; write nothing and spend nothing. |

## Observe

Read state before running new work.

```zsh
uv run siro summarize-runs runs/attempts.jsonl
uv run siro summarize-research
uv run siro provider-report --model-calls runs/model_calls.jsonl
uv run siro list-approvals --status pending
```

## Run Experiments

```zsh
# Goal 02: code inner loop
uv run siro run-task tasks/code_improver/task_001 -n 5

# Goal 06: bounded training inner loop
uv run siro run-training tasks/training/task_001 --budget 8

# Goal 08: full role chain
uv run siro run-org tasks/code_improver/task_001 --objective "Make sum_list simpler"

# Goal 09: research suite
uv run siro run-research
uv run siro run-research packs/ml/tasks/training/tiny_mlp --config config/tier0.local.yaml
```

Use `--config config/tier1.frontier.yaml` for frontier roles. Use
`--config config/tier0.local.yaml` to force local execution.

## Propose Process Changes

```zsh
uv run siro propose-meta-change runs/attempts.jsonl
```

The meta loop can propose prompt/retrieval/selection changes and A/B-test them. Durable
application remains human-gated.

## Governed Scale-Up

```zsh
uv run siro --dry-run run-scaled packs/ml/tasks/training/tiny_mlp --compute-tier 1
uv run siro run-scaled packs/ml/tasks/training/tiny_mlp --compute-tier 1
uv run siro sandbox-backends
uv run siro run-scaled --compute-tier 1 --backend linux_guarded
```

Compute tier > 0 requires:

- a recorded pass at the next-smaller tier
- a human approval bound to `(experiment, tier)`

## Model Training And Deploy

```zsh
uv run siro train-model exp1 --learning-rate 0.1 --epochs 300
uv run siro deploy-model <artifact_id> implementation \
    --implementation-provider anthropic \
    --reviewer-provider openai
```

Training requires Tier 2, stability checks, and `MODEL_TRAIN` approval. Deployment requires a
separate `MODEL_DEPLOY` approval and cross-model review.

## Approvals

```zsh
uv run siro request-approval budget_increase --target max_usd_per_run \
    --payload '{"max_usd_per_run":20}' \
    --rationale "pilot needs headroom"

uv run siro list-approvals --status pending
uv run siro approve <request_id> --by alice
uv run siro deny <request_id> --by alice --reason "insufficient evidence"
uv run siro revoke <decision_id> --by alice --reason "rolled back"
```

Signed identity-checked approvals:

```zsh
uv run siro create-operator alice --display-name "Alice Reviewer" --role approver
uv run siro list-operators
uv run siro approve <request_id> --by alice --signing-key "$LOCAL_DEV_SIGNING_KEY" \
    --config config/tier2.governed.yaml
uv run siro verify-governance --config config/tier2.governed.yaml
uv run siro export-governance-packet <request_id> --config config/tier2.governed.yaml
```

## Pilot

```zsh
uv run siro pilot-init
uv run siro pilot-run
uv run siro pilot-run --include-conditional
uv run siro pilot-report
```

The pilot compares fixed Tier 0, cheap-frontier, and optional strong-frontier arms under
budget caps. The report recommends continue/revise/stop; it does not approve scale-up.

## Storage And Audit

```zsh
uv run siro storage-migrate --store runs/siro.db
uv run siro storage-import --store runs/siro.db
uv run siro storage-export --store runs/siro.db --to-dir runs/export
uv run siro storage-verify --store runs/siro.db
uv run siro summarize-runs --store runs/siro.db
```

JSONL is default. SQLite adds migrations, dedupe, hash chains, and import/export.

## Maintenance

```zsh
uv run siro check-docs
mise run check-docs
uv run siro pricing-audit --config config/tier1.frontier.yaml --strict
mise run pricing-audit
uv run pytest tests/test_cli.py::test_tier2_model_training_smoke_path_uses_separate_train_and_deploy_approvals
```

## Command Index

| Command(s) | Goal | Purpose |
|---|---|---|
| `run-task` | 02 / 07 | Code inner loop. |
| `run-training` | 06 | Fixed-MLP training loop. |
| `propose-meta-change` | 05 | Bounded process-change proposal. |
| `run-org` | 08 | Full role-chain cycle. |
| `run-research`, `summarize-research` | 09 | Research tasks and suite summary. |
| `request-approval`, `list-approvals`, `approve`, `deny`, `revoke` | 10 | Approval workflow. |
| `run-scaled` | 11 / 15 | Governed compute budget and isolation backend. |
| `train-model`, `deploy-model` | 12 | Governed training and deployment. |
| `check-docs` | 13 | Docs/manifest/privacy checks. |
| `pricing-audit` | 14 | Pricing and budget audit. |
| `sandbox-backends` | 15 | Isolation backend availability. |
| `storage-migrate`, `storage-import`, `storage-export`, `storage-verify` | 16 | SQLite store and audit. |
| `summarize-runs` | 01 / 16 | Attempt archive summary. |
| `provider-report` | 18 | Spend, latency, retry, and error report. |
| `create-operator`, `list-operators`, `revoke-operator`, `verify-governance`, `export-governance-packet` | 19 | Identity-backed governance. |
| `pilot-init`, `pilot-run`, `pilot-report` | 20 | Bounded pilot and report. |
