# 00 — Principles

## Objective

Build a bounded research automation system that can improve the process of conducting machine learning and software experiments.

The system should recursively improve **research workflow quality**, not recursively create uncontrolled successor models.

## Core thesis

A self-improving research organization is a loop:

```text
better research agent
→ better experiment selection
→ better code and evals
→ better research memory
→ better future research agent behavior
```

In the strongest version, model improvements also feed back into the system:

```text
better model
→ better AI researcher
→ better training/evaluation process
→ better model
```

The project should begin with the weaker and safer loop:

```text
local model
→ better code/eval/prompt strategies
→ better local research loop
```

and then graduate — without changing the loop mechanics or safety contract — to a frontier-LLM-driven organization that can actually conduct research-shaped work:

```text
frontier model (Claude / GPT) as research agent
→ real hypotheses, plans, implementations, interpretations
→ better research org behavior
```

## Capability tiers and provider agnosticism

The system is **model-provider agnostic**: the same agents, lifecycle, gates, and memory run whether a role is backed by a local model or a frontier lab model. Capability grows through explicit **tiers**, each widening capability *and* tightening governance (`07_model_providers_and_tiers.md`):

- **Tier 0** — fully local, offline, strongest safety posture; validates the machinery.
- **Tier 1** — frontier LLMs prototype the full organization; network egress is allow-listed to model providers only, and candidate execution stays offline (`08_frontier_prototype_architecture.md`).
- **Tier 2** — governed scale-up; every step beyond Tier 1 is human-gated.

Lowering the tier must always be safe and require config only, never code changes.

## Design principles

1. **Objective evaluation first**
   - Favor tests, benchmarks, simulations, static analysis, type checks, and reproducible metrics.
   - Avoid relying on self-judgment as the primary signal.

2. **Constrained edit surfaces**
   - Agents may edit only approved modules.
   - Critical infrastructure, evaluator logic, and safety controls require human approval.

3. **Promotion through gates**
   - Ideas must pass small tests before receiving larger budgets.
   - No direct jump from speculative hypothesis to expensive training run.

4. **Research memory as infrastructure**
   - Every experiment must produce structured records.
   - Negative results are first-class data.

5. **Human authority over escalation**
   - Agents can propose.
   - Evaluators can score.
   - Humans approve high-budget, high-risk, or irreversible actions.

6. **Reproducibility over vibes**
   - Every result must be replayable.
   - Every promoted change must have a traceable lineage.

7. **Safety and capability are co-evaluated**
   - Capability wins do not count if they create unacceptable safety regressions.

8. **Provider-agnostic, tier-gated capability**
   - Any agent role may be backed by a local or frontier model via configuration.
   - More capable models (and the network access they require) come with stricter gates, not looser ones.
   - The control plane (agent reasoning) and execution plane (candidate code) are isolated: only the control plane may reach the network, and only to allow-listed model providers.

## Non-goals

This project should not attempt to:

- Create an unrestricted self-replicating agent.
- Allow autonomous access to arbitrary cloud compute.
- Allow unrestricted network egress; only allow-listed model-provider endpoints are permitted, and only from the control plane.
- Place API keys, credentials, or full datasets in the candidate execution plane or in model prompts.
- Allow agents to disable logs, modify evaluators, or bypass safety gates.
- Treat benchmark score increases as proof of general intelligence.
- Fine-tune model weights before the scaffold, evaluator, and audit systems are stable.
