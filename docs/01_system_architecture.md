# 01 — System Architecture

## Overview

The self-improving research organization is composed of five layers:

```text
┌────────────────────────────────────────────┐
│ Human governance and review                 │
├────────────────────────────────────────────┤
│ Research controller / orchestration layer   │
├────────────────────────────────────────────┤
│ Specialized research agents                 │
├────────────────────────────────────────────┤
│ Experiment execution and evaluation layer   │
├────────────────────────────────────────────┤
│ Research memory and audit ledger            │
└────────────────────────────────────────────┘
```

## Layer 1: Human governance

Responsibilities:

- Define research objectives.
- Approve high-compute experiments.
- Approve changes to evaluators and safety controls.
- Review meta-research changes.
- Stop or roll back unsafe behavior.

## Layer 2: Research controller

Responsibilities:

- Select research agenda items.
- Assign tasks to specialized agents.
- Enforce budget limits.
- Manage experiment queues.
- Route results to evaluation and memory.
- Escalate decisions requiring human review.

## Layer 3: Specialized agents

Example agents:

- Hypothesis Agent
- Literature Agent
- Implementation Agent
- Experiment Runner Agent
- Evaluation Agent
- Safety Agent
- Interpretation Agent
- Memory Curator Agent
- Meta-Research Agent

Each agent has a constrained role, input contract, output contract, and permission set. Each agent is backed by a model through a **provider abstraction** (`07_model_providers_and_tiers.md`): the role logic is identical whether the model is local (llama.cpp / LlamaBarn) or a frontier lab model (Claude, GPT). Provider, model, and budget are configuration; capability requirements are declared per role and bound to a concrete model by the active tier.

## Control plane vs execution plane

Cutting across all layers is a hard isolation boundary that becomes load-bearing once frontier APIs are used:

- **Control plane** — orchestrator and agents (reasoning). May reach the network, but only allow-listed model-provider endpoints. Holds credentials. Never runs untrusted candidate code.
- **Execution plane** — candidate code, tests, and training scripts. No network, temp dir, subprocess timeouts, read-only evaluator/safety code, no credentials in the environment.

Models produce text, structured proposals, or patches; the controller — not the model — runs fixed, vetted commands in the execution plane. See `08_frontier_prototype_architecture.md`.

## Layer 4: Experiment execution and evaluation

Responsibilities:

- Run code in sandboxes.
- Execute tests and benchmarks.
- Enforce timeouts and resource limits.
- Capture logs, artifacts, metrics, and failures.
- Compare against baselines.

## Layer 5: Research memory and audit ledger

Responsibilities:

- Store experiment hypotheses.
- Store code diffs and environment metadata.
- Store metrics and evaluator outputs.
- Store interpretations and follow-up recommendations.
- Track lineage from idea → experiment → result → promoted change.

## Core data flow

```text
research objective
→ hypothesis generation
→ experiment plan
→ code implementation
→ sandbox execution
→ evaluation
→ safety review
→ interpretation
→ memory write
→ next hypothesis
```

## Recursive component

The system becomes self-improving when it can propose and validate improvements to:

- Prompt templates
- Agent role definitions
- Experiment selection policies
- Memory retrieval policies
- Mutation/crossover strategies
- Evaluation coverage
- Test generation methods
- Budget allocation heuristics

These meta-changes should require stricter review than ordinary task-level experiment changes.
