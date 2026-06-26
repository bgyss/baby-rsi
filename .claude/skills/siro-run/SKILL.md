---
name: siro-run
description: Run a siro experiment (the inner/outer loops) at the right tier with safe defaults. Use when the user wants to improve a function, tune training, run the full org, run the research suite, propose a meta-change, or scale up compute. Maps a plain-language ask to the correct `uv run siro` command and reports the objective outcome.
---

# Run a siro experiment

Map the user's intent to one command, default to **Tier 0** (local/offline/free) unless
they ask for frontier, run it, then report the *objective* outcome (promoted or not, and
why) — never a model-judgment claim. Auto-commit any resulting change with `jj describe` /
`jj new`; do not push.

## Choose the command

| The user wants to… | Command |
|---|---|
| Improve one function against its tests | `uv run siro run-task <task_dir> -n 5` |
| Tune a training config (fixed MLP, wall-clock budget) | `uv run siro run-training <task_dir> --budget 8` |
| Route one objective through the whole org | `uv run siro run-org <task_dir> --objective "<goal>"` |
| Run the research suite (all tasks) or one task | `uv run siro run-research [<task_dir>]` |
| Improve the *process* itself (prompts/retrieval/selection) | `uv run siro propose-meta-change runs/attempts.jsonl` |
| Run a research eval under a governed compute budget | `uv run siro run-scaled <task_dir> --compute-tier N` |

Task dirs live under `tasks/code_improver/`, `tasks/training/`, and
`tasks/research/<family>/<task>/`. If unsure which tasks exist, list those directories.

## Tier selection (config-only)

- Default / explicit local: `--config config/tier0.local.yaml`
- Frontier: `--config config/tier1.frontier.yaml` (network egress limited to model
  providers; candidate execution still offline). Tell the user you're going frontier.
- `run-task`/`run-training` default to Tier 0; `run-org`/`run-research` default to Tier 1.
  **Pass an explicit `--config` so the tier is never a surprise.**

## Governed scale-up (`run-scaled`, Tier 2)

`--compute-tier 0` is free. **Any higher tier needs a human approval bound to
`(experiment, tier)` plus a recorded pass at the next-smaller tier.** If `run-scaled`
raises `GovernanceDenied` or `ComputeAllocationError`, do **not** try to work around it —
hand off to **/siro-govern** to get the approval, then retry. Same for `train-model` /
`deploy-model` (those are governed; prefer **/siro-govern** to set up the approvals first).

## After running

1. State the objective result plainly: promoted? primary metric delta? which gate failed
   (safety / reproducibility / hidden-test / edit-surface) if not?
2. If a budget ceiling tripped (`BudgetExceeded`) or governance denied, **halt and
   escalate** — report it, don't retry blindly.
3. Record the change: `jj describe -m "..."` (with the project co-author/session trailers)
   then `jj new`. Never `jj git push` without the user asking.
4. Offer **/siro-watch** to see the run in the context of overall suite health.
