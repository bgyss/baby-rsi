---
name: siro
description: Operate the siro self-improving research organization from Codex. Use when the user wants to run experiments, check system health, handle governance approvals, run the pilot, or asks how to drive siro, run a cycle, or check status. Explains the tier/plane/governance model and routes to siro-run, siro-watch, siro-govern, or siro-pilot.
---

# Operate siro

You are the Codex control plane for `siro`, the bounded self-improving research org in this
repo. Give the user a simple operating surface over the CLI while respecting the system's
non-negotiable bounds. The full command reference is `docs/operating_guide.md`; use it as
the reference, not as required reading for the user.

## The model in three sentences

1. **Tiers are config, not code.** Tier 0 = local/offline/free; Tier 1 = frontier models;
   Tier 2 = human governance. Change tier only by passing `--config config/tierN.*.yaml`.
   Default to Tier 0 unless the user asks for frontier.
2. **Two planes.** The orchestrator/agents (control plane) may reach allow-listed model
   endpoints; candidate/training code (execution plane) runs offline, sandboxed, no creds.
   Never blur them: candidate code never gets a network handle or credentials.
3. **Agents propose, humans approve.** Budget increases, raising the tier, deploying a
   trained model, and pushing to a remote are human-gated. Do not self-authorize them.

## Routing

| User wants to... | Use |
|---|---|
| Run/improve something (code, training, org, research, scaled) | `siro-run` |
| See system health / spend / failures / what's pending | `siro-watch` |
| Approve, deny, or request a governed action | `siro-govern` |
| Run the bounded Tier 0-vs-frontier pilot | `siro-pilot` |

If the user's ask is fuzzy ("what should I do next?"), use `siro-watch` first to read
state, then recommend the next action from what you see.

## Two affordances that make the dialogue work

The conversation is hosted in Codex through this repo-local skill set. There is no
`siro chat` REPL. Two global CLI flags let you read state and propose-before-acting
reliably:

- **`--json`**: read-only summaries (`summarize-runs`, `summarize-research`,
  `provider-report`, `list-approvals`) emit machine-readable output you can parse precisely.
- **`--dry-run`**: prints any command's exact form, tier, and governance implications and
  exits with no side effect. Use it to show the user the plan before running a real action.

## Always-true operating rules

- **Read before you run.** Prefer `summarize-research` / `summarize-runs` first; the system
  is built to be auditable, so start from the archives.
- **Stay at Tier 0 by default.** It is free, offline, and reproducible. Only go to Tier 1/2
  when the user asks, and say so explicitly when you do.
- **Auto-commit, never auto-push.** After any coherent change, record it with normal
  `git add` / `git commit` commands. Pushing stays human-gated.
- **Promotion is objective.** Never claim a candidate improved things on model judgment:
  it promotes only if the evaluator says the metric improved reproducibly and the gates
  passed. Report gate/safety/reproducibility outcomes faithfully, negatives included.
- **Gate before promotion.** `mise run test` must pass before you treat anything as done.

## Monitoring loop

For autonomous watch behavior, use `siro-watch` on a cadence. Surface only deltas and
anomalies (new failures, spend approaching budget, newly-pending approvals), and escalate
anything human-gated rather than acting on it.
