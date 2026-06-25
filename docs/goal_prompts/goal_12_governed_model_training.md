# Goal Prompt 12 — Governed Model-Training (Weight-Update) Experiments

## Goal

Close the **strongest loop** — "better model → better researcher → better training process →
better model" (`../00_principles.md`) — but fully bounded. Let the organization run genuine
model-training / weight-update experiments under the strictest governance, where a trained
model is an *artifact with lineage*, never an automatically-deployed successor. This is the
"possibly model-training experiments" capability of Tier 2 (`../07_model_providers_and_tiers.md`),
and it is the most sensitive capability in the project, so it carries the most gates.

Depends on Goals 06, 10, 11.

## Requirements

- Extend the training loop (Goal 06) from tuning a fixed benchmark's hyperparameters to
  producing candidate **model weights**, scored by objective held-out metrics. Training runs
  in the offline execution plane with no network and no credentials, under the compute tiers
  and checkpointing of Goal 11.
- **Stability precondition** (`../00_principles.md` non-goal: "Fine-tune model weights before
  the scaffold, evaluator, and audit systems are stable"): a weight-producing run is permitted
  only when the evaluator, audit ledger, and gates are green and stable. Absent that, training
  is refused — independently of any approval.
- **Governance-gated start**: every weight-update experiment requires a matching Goal 10
  approval *and* the stability precondition; otherwise it is blocked and escalated.
- **Artifacts with lineage**: produced weights are stored with full reproducible lineage
  (training data id + seed, config, base-model hash, code version) in a dedicated artifact
  store and recorded in an archive (including negative results).
- **No auto-deploy**: a trained model is **never** bound to an agent role automatically.
  Promoting a candidate model into the org's `agent_models` is a *separate*, human-approved
  governance action, with cross-model review. Trained weights are data, not control-plane
  code; a candidate-produced model never silently becomes a model client.
- Objective held-out metrics decide quality; no model self-judgment; reproducible.

## Acceptance criteria

- A weight-update experiment cannot start without **both** a governance approval (Goal 10)
  **and** the stability precondition met; otherwise it is blocked and recorded as a pending
  escalation (assert in tests).
- Produced weights carry full reproducible lineage and land in the artifact store + archive;
  negative results are recorded, never discarded.
- A trained model is **never** auto-bound to an agent role; binding requires a separate human
  approval (assert in tests) and cross-model review.
- Held-out objective metrics decide promotion; a rerun reproduces the result.
- The capability is fully **disabled at Tier ≤ 1** and is config + approval, never code;
  lowering the tier is always safe.

## Constraints

- Offline execution plane only — no network, no credentials, hard resource ceilings; no
  autonomous package install.
- Never weaken the evaluator, audit ledger, or gates to permit training — the stability
  precondition is a gate, not a suggestion.
- Humans approve every weight-producing run and every deployment of a trained model;
  deployment gets cross-model review and is irreversible-by-default (kept behind the gate).
- Negative results are first-class data; objective evaluation decides, never self-judgment.

## Self-improvement

This goal makes the strongest self-improvement loop (`../00_principles.md`) available *only*
through the bounded cycle of `../13_self_improvement_loop.md` — a trained model can improve
the org, but never on the loop's own authority.

- **Records**: every training attempt, its lineage, and its objective metrics (including
  negatives) to the artifact store, archive, and memory.
- **Reflects / proposes**: the loops may propose a weight-update experiment or the deployment
  of a trained model; both surface as governance requests, never applied changes.
- **Validated / gated**: objective held-out metrics score first; deployment of any trained
  model requires cross-model review plus human approval before it can back an agent role.
- **Bounds**: per `../13_self_improvement_loop.md` — changing the model behind a role,
  deploying trained weights, and expanding compute/budget/tier are all human-gated, and
  these meta-level changes get the strictest review in the project.
