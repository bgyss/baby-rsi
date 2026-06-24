# 08 — Frontier-LLM Research Organization Prototype (Tier 1)

## Goal

Run the **full** research organization — not just a code-mutation loop — with frontier LLMs (Claude, GPT) acting as the specialized agents, while preserving every safety invariant from the local testbed. This is the target the whole project builds toward; the local testbed (`09_local_testbed_architecture.md`) exists to make this safe to attempt.

Frontier models change what is tractable: at Tier 0 a small local model can only do bounded code repair; at Tier 1 the same loop can do genuine hypothesis generation, literature-grounded reasoning, multi-file implementation, honest interpretation, and meta-research over its own process.

## What "full organization" adds over the code-improver loop

| Capability | Tier 0 (local) | Tier 1 (frontier) |
|---|---|---|
| Hypotheses | Templated repair prompts | Open-ended, literature-grounded, falsifiable ideas |
| Planning | Implicit | Explicit experiment plans with predicted outcomes |
| Implementation | Single-function rewrite | Multi-file patches against allowed surfaces |
| Evaluation | Objective scorer only | Objective scorer + model-written regression narrative |
| Interpretation | Score deltas | Mechanistic explanation, ablation proposals, honest uncertainty |
| Safety review | Static scan | Static scan + cross-model adversarial review |
| Meta-research | Heuristic tweaks | Reasoned process redesign with A/B validation |

The loop, lifecycle, gates, and memory schema are **unchanged**. Only the agents behind the roles get more capable, and governance tightens accordingly.

## Agent topology

```text
                         ┌──────────────────────────┐
                         │   Human governance        │
                         │   (objectives, approvals) │
                         └────────────┬──────────────┘
                                      │
                         ┌────────────▼──────────────┐
                         │   Orchestrator / Controller│  (control plane)
                         │   - agenda + budget        │
                         │   - routing + escalation   │
                         │   - token/cost accounting  │
                         └─┬───┬───┬───┬───┬───┬───┬──┘
       ┌──────────┬────────┘   │   │   │   │   │   └────────┬──────────┐
       ▼          ▼            ▼   ▼   ▼   ▼   ▼            ▼          ▼
  Hypothesis  Literature  Implementation  Eval  Safety  Interpretation  Meta-
   Agent       Agent        Agent        Agent  Agent     Agent       Research
  (Claude)    (Claude)      (Claude)     (local) (GPT)    (Claude)     (Claude)
                                  │
                                  ▼
                    ┌───────────────────────────┐
                    │  Execution plane (sandbox) │  no network, timeouts,
                    │  runs candidate + tests    │  read-only evaluator
                    └───────────────────────────┘
                                  │
                                  ▼
                    Research memory + audit ledger
```

Each agent is a frontier (or local) model invoked through the provider abstraction (`07_model_providers_and_tiers.md`) with:

- a **role system prompt** (in `prompts/`),
- a typed **input contract** and **output schema** (Pydantic; enforced via structured output),
- a constrained **tool set** (tools are control-plane functions, e.g. `read_allowed_file`, `propose_patch`, `query_memory` — never raw shell or network), and
- explicit **forbidden actions** mirrored from `03_agent_roles.md`.

Agents emit structured proposals; the orchestrator validates them against schemas and gates before anything executes.

## End-to-end research cycle

```text
human objective
→ orchestrator selects agenda item + budget tier
→ Hypothesis Agent proposes falsifiable idea (+ predicted result, expected failure)
→ Literature Agent grounds it against references + prior memory (dedupe, prior art)
→ orchestrator triages (cheap? clear metric? low risk? non-duplicate?)
→ Implementation Agent emits a patch limited to allowed edit surfaces
→ Code-integrity gate + static safety scan (control plane)
→ execution plane runs candidate + tests under timeout, no network
→ objective evaluator scores; Evaluation Agent writes regression narrative
→ Safety Agent (cross-model) reviews diff, logs, tool use
→ Interpretation Agent explains result, proposes next action, drafts memory entry
→ promotion gate (metric ↑, no regression, safety pass, reproducible, edit-legal)
→ Memory Curator writes structured record (successes AND negative results)
→ orchestrator updates agenda; Meta-Research Agent periodically proposes process changes
```

This is the same lifecycle as `04_experiment_lifecycle.md`; the frontier agents fill the previously-thin reasoning steps.

## Multi-model diversity and adversarial review

Frontier prototyping should deliberately mix providers:

- The **Safety Agent and Evaluation review should use a different model/provider than the Implementation Agent** so a single model's blind spots or reward-hacking tendencies are caught by another.
- Run hypothesis generation across two providers occasionally to maintain idea diversity and counter local-optimum collapse (`11_risks_and_controls.md`).
- Disagreement between models on a promotion decision is an escalation signal, not noise.

## Frontier-specific risks (additions to `11_risks_and_controls.md`)

- **Prompt injection via task content, memory, or tool output.** Untrusted experiment text or retrieved memory could try to steer an agent. Controls: treat all retrieved/tool content as data not instructions; keep credentials and high-permission tools off agents that read untrusted content; structured outputs constrain action space.
- **Data exfiltration through API calls.** The control plane can reach the network. Controls: egress allowlist to provider endpoints only; never place secrets, full datasets, or evaluator internals into prompts; log every outbound call.
- **Persuasive overclaiming.** Frontier models write convincingly. Controls: objective evaluator is authoritative; require metric tables + reproduction commands; separate Interpretation from Evaluation; cross-model check.
- **Cost runaway.** Controls: token/USD ceilings per run and per day with halt-and-escalate (`07_model_providers_and_tiers.md`).
- **Capability-driven autonomy creep.** More capable agents may propose broadening their own permissions. Controls: permission/budget/evaluator/safety changes remain human-gated; meta-changes are high-risk by default.

## Acceptance criteria for the Tier 1 prototype

- Every agent role can be backed by Claude or GPT via config, with at least one role still able to run on a local model.
- A full cycle (hypothesis → … → memory write) completes on a real research-shaped task using frontier agents.
- All candidate execution remains offline and sandboxed; only the control plane reaches allow-listed endpoints.
- Safety review uses a different provider than implementation.
- Token/cost budgets are enforced and every model call is in the audit ledger.
- Dropping `tier: 1` → `tier: 0` in config returns the system to fully-local operation with no code changes.
