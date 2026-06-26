# Operating guide

A task-oriented walkthrough of the `siro` command surface, organized as a learning
flow rather than a flat list. If you just want to *drive* the system from inside Claude
Code, prefer the repo-local skills in [`.claude/skills/`](../.claude/skills/) — they wrap
these commands behind five intuitive verbs (`/siro`, `/siro-run`, `/siro-watch`,
`/siro-govern`, `/siro-pilot`). This guide is the reference those skills lean on, and the
place to look when you want the exact flags.

The canonical interface is `uv run siro <command>`; the `mise run ...` tasks are thin
wrappers. Run `uv run siro --help` (or `uv run siro <command> --help`) at any time.

Two global flags (Goal 21) make the surface conversational — they let the skills (and you)
*read state precisely* and *propose before acting*:

- **`--dry-run`** prints the exact command, its tier, and its governance implications, then
  exits **without** any state change, spend, or ledger write. Use it to preview anything:
  `uv run siro --dry-run run-scaled --compute-tier 1`.
- **`--json`** makes the read-only summaries (`summarize-runs`, `summarize-research`,
  `provider-report`, `list-approvals`) emit machine-readable output instead of prose:
  `uv run siro --json summarize-research`. The default human-readable output is unchanged.

The conversation itself is hosted in Claude Code by the skills — there is no `siro chat`
REPL; the CLI stays non-interactive and scriptable.

## Mental model (read this first)

Three ideas explain every command:

- **Tiers are config, not code.** Tier 0 is fully local and offline (free), Tier 1 adds
  frontier models for the reasoning roles, Tier 2 adds human governance. You move between
  tiers only by passing a different `--config config/tierN.*.yaml`. Lowering a tier is
  always safe. Default to Tier 0 while learning.
- **Control plane vs execution plane.** The orchestrator and agents (control plane) may
  reach allow-listed model endpoints and hold credentials; they never run candidate code.
  Candidate/training code (execution plane) runs offline, in a temp dir, under a hard
  timeout, with no network and no credentials. Nothing you run here crosses that line.
- **Agents propose, humans approve.** Every irreversible or high-risk step — a budget
  increase, raising the tier, deploying a trained model, pushing to a remote — is gated on
  an explicit human approval recorded in an append-only ledger. No agent command grants
  itself permission.

Everything below is a different entry point into the same loop:
**propose → sandbox → evaluate → archive → select → record.**

## 1. Set up the environment

```zsh
nix develop        # or: direnv allow  (auto-enters via .envrc)
mise install       # python 3.11 + uv at pinned versions
mise run sync      # uv sync — install Python deps
mise run test      # uv run pytest — gate before any promotion
```

## 2. Observe — read the archives before you run anything

The system is built to be auditable, so start by reading state. These commands are
read-only and safe to run any time.

```zsh
uv run siro summarize-runs runs/attempts.jsonl                 # reflect on the code-loop archive
uv run siro summarize-research                                 # per-family research suite summary
uv run siro provider-report --model-calls runs/model_calls.jsonl  # spend / latency / retries / errors
uv run siro list-approvals --status pending                   # outstanding human-gated requests
```

`summarize-research` reports, per family: accepted/promoted/mixed/failed counts, median
cycles to success, safety-gate / hidden-test / reproducibility failures, token + USD
spend, strategy diversity, and cost per promotion. This is your primary health view.

## 3. Run an experiment (the inner loop)

Start at Tier 0 (local, offline, free). Each command runs the same lifecycle; they differ
only in *what* is being improved. Pass `--config config/tier1.frontier.yaml` to run the
same thing with frontier models, or `--config config/tier0.local.yaml` to force local.

```zsh
# Code: improve one function against its tests (Goal 02)
uv run siro run-task tasks/code_improver/task_001 -n 5

# Training: tune a bounded TrainConfig for a fixed pure-Python MLP (Goal 06)
uv run siro run-training tasks/training/task_001 --budget 8

# Full org: route one objective through every role end-to-end (Goal 08)
uv run siro run-org tasks/code_improver/task_001 --objective "Make sum_list simpler"

# Research suite: omit the task dir to run one cycle on every discovered task (Goal 09)
uv run siro run-research
uv run siro run-research tasks/research/training/tiny_mlp --config config/tier0.local.yaml
```

Promotion is decided by the objective evaluator, not model self-judgment: a candidate is
promoted only if it improves the primary metric, doesn't regress required secondaries,
passes the safety gate, is reproducible, and respected its edit surface.

## 4. Reflect and propose process changes (the meta loop)

The outer loop improves the *process* (prompts, retrieval, selection) under the same gates
and a stricter review. It only proposes; durable application stays human-gated.

```zsh
uv run siro propose-meta-change runs/attempts.jsonl   # A/B a reversible process change (Goal 05)
```

## 5. Scale up under governance (Tier 2)

Beyond Tier 1, more compute and stronger loops are gated. The pattern is always: a recorded
pass at the next-smaller step, **plus** a human approval bound to the exact change.

```zsh
# Compute scale-up: tier 0 is free; higher tiers require an approval bound to (experiment, tier)
uv run siro run-scaled tasks/research/training/tiny_mlp --compute-tier 1
uv run siro sandbox-backends                                   # list isolation backends + availability
uv run siro run-scaled --compute-tier 1 --backend linux_guarded  # hard OS-enforced isolation where available
```

### Governed model-training and deploy (Goal 12 — the strongest loop)

```zsh
uv run siro train-model exp1 --learning-rate 0.1 --epochs 300  # only with stability green + MODEL_TRAIN approval
uv run siro deploy-model <artifact_id> implementation \
    --implementation-provider anthropic --reviewer-provider openai  # separate MODEL_DEPLOY approval + cross-model review
```

A trained model is never auto-deployed: binding it to a role needs a separate
`MODEL_DEPLOY` approval and a reviewer on a different provider than the implementation.

## 6. The human approval workflow (governance)

Agents request; humans decide. Requests and decisions live in `runs/approvals.jsonl`.

```zsh
# 1. A governed action records a pending request (here, a budget increase)
uv run siro request-approval budget_increase --target max_usd_per_run \
    --payload '{"max_usd_per_run":20}' --rationale "pilot needs headroom"

# 2. A human reviews what's pending
uv run siro list-approvals --status pending

# 3. A human decides (approve / deny / revoke are human-only verbs)
uv run siro approve <request_id> --by alice
uv run siro deny <request_id> --by alice --reason "insufficient evidence"
uv run siro revoke <decision_id> --by alice --reason "rolled back"
```

### Identity-validated governance (Goal 19)

For signed, identity-checked approvals at Tier 2, register operators and sign proofs:

```zsh
uv run siro create-operator alice --display-name "Alice Reviewer" --role approver
uv run siro list-operators
uv run siro approve <request_id> --by alice --signing-key "$LOCAL_DEV_SIGNING_KEY" \
    --config config/tier2.governed.yaml                       # identity-validated signed proof
uv run siro verify-governance --config config/tier2.governed.yaml  # verify identities, hashes, signatures
uv run siro export-governance-packet <request_id> --config config/tier2.governed.yaml  # audit packet
```

## 7. Run the bounded operational pilot (Goal 20)

A fixed, budget-capped comparison of Tier 0 / cheap-frontier / strong-frontier arms,
ending in a cost-per-promotion report with a continue/revise/stop recommendation. It
approves no scale-up by itself.

```zsh
uv run siro pilot-init                  # write the fixed plan + command transcript
uv run siro pilot-run                   # run the required arms into per-arm archives
uv run siro pilot-run --include-conditional   # also run the strong-frontier follow-up
uv run siro pilot-report                # render the Markdown cost-per-promotion report
```

## 8. Durable storage and audit (Goal 16)

JSONL is the default transparent backend. Opt into SQLite for migrations, dedupe, and
hash-chained tamper-evidence; export stays byte-compatible with the JSONL readers.

```zsh
uv run siro storage-migrate --store runs/siro.db              # create / upgrade the SQLite store
uv run siro storage-import --store runs/siro.db               # idempotently load JSONL archives
uv run siro storage-export --store runs/siro.db --to-dir runs/export  # SQLite -> JSONL backup
uv run siro storage-verify --store runs/siro.db               # verify governance/artifact hash chains
uv run siro summarize-runs --store runs/siro.db               # summaries read JSONL or SQLite
```

## 9. Keep the contracts honest (maintenance)

```zsh
uv run siro check-docs                                        # README / manifest / goal-prompt / privacy
mise run check-docs                                           # thin wrapper
uv run siro pricing-audit --config config/tier1.frontier.yaml --strict  # pricing freshness + budget audit
mise run pricing-audit                                        # thin wrapper

# Cheap Tier 2 smoke that the train/deploy approval split holds:
uv run pytest tests/test_cli.py::test_tier2_model_training_smoke_path_uses_separate_train_and_deploy_approvals
```

## Command index by goal

| Command(s) | Goal | What it does |
|---|---|---|
| `run-task` | 02 / 07 | Per-task code inner loop (Tier 0, or Tier 1 by config). |
| `run-training` | 06 | Per-task training inner loop (fixed MLP, wall-clock budget). |
| `propose-meta-change` | 05 | Meta-research outer loop (A/B a reversible process change). |
| `run-org` | 08 | One full frontier-org research cycle. |
| `run-research`, `summarize-research` | 09 | Research-shaped task suite + per-family summary. |
| `request-approval`, `list-approvals`, `approve`, `deny`, `revoke` | 10 | Governance request/decision workflow (human-only verbs). |
| `run-scaled` | 11 / 15 | Eval under a governed compute budget + isolation backend. |
| `train-model`, `deploy-model` | 12 | Governed weight-update + gated deploy. |
| `check-docs` | 13 | Docs/README/manifest/privacy consistency contract. |
| `pricing-audit` | 14 | Model-pricing freshness and budget audit. |
| `sandbox-backends` | 15 | List resource-isolation backends + availability. |
| `storage-migrate`, `storage-import`, `storage-export`, `storage-verify` | 16 | Durable SQLite store and audit. |
| `summarize-runs` | 01 / 16 | Reflect on the attempts archive (JSONL or SQLite). |
| `provider-report` | 18 | Provider spend / latency / retry / error report. |
| `create-operator`, `list-operators`, `revoke-operator`, `verify-governance`, `export-governance-packet` | 19 | Operator identity + signed-approval governance. |
| `pilot-init`, `pilot-run`, `pilot-report` | 20 | Bounded operational pilot + cost-per-promotion report. |
