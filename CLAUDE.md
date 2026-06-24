# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

`baby-rsi` is the **design specification** for a bounded, auditable self-improving research organization — a multi-agent system that proposes ML/software experiments, runs them in a sandbox, scores them against objective evaluators, and preserves structured research memory under explicit safety gates. The intended (future) implementation is a Python package named `siro`.

As of now this repo contains **only the spec and goal prompts — no code has been implemented yet.** When you implement, you are building the system the docs describe; the docs are the source of truth, not legacy.

The design lives under `docs/`: the numbered `docs/NN_*.md` files (`00_principles` → `12_references`), which `README.md` maps. `docs/goal_prompts/goal_0N_*.md` are the staged build instructions — implement them **in order**. Goals `01`–`06` build the local Tier 0 testbed (start at `docs/goal_prompts/goal_01_project_scaffold.md`); goals `07`–`09` generalize the model layer to frontier providers and stand up the full Tier 1 organization. Each goal prompt carries its own acceptance criteria and constraints that take precedence over general intuition. Implementation code (the `siro` package) belongs at the repo root (`src/`, `tests/`, `tasks/`), not under `docs/`.

## Capability tiers (the central organizing idea)

The same loop, lifecycle, gates, and memory run at every tier; only the models behind the agents and the governance around them change (`docs/07_model_providers_and_tiers.md`, `docs/08_frontier_prototype_architecture.md`):

- **Tier 0** — fully local/offline (Ollama). Validates the machinery. `docs/09_local_testbed_architecture.md`.
- **Tier 1** — frontier LLMs (Claude/GPT) prototype the full research org. Network egress is allow-listed to model providers only; candidate execution stays offline.
- **Tier 2** — governed scale-up; human-gated. Aspirational.

The system is **provider-agnostic**: any role binds to a local or frontier model via config (`agent_models`), never hardcoded. Selecting/lowering a tier is **config-only** — never a code change. Lowering the tier must always be safe.

## Version control — prefer jj

This repo uses **[jujutsu (`jj`)](https://jj-vcs.github.io/jj/) as the primary VCS**, colocated with git (both a `.jj/` and `.git/` directory are present, sharing one working copy). **Default to `jj` commands; reach for `git` only when something has no jj equivalent.** Because the backend is git, any `git` operation still works and stays in sync, but routine work should go through jj.

Common mappings:

| Task | jj |
|---|---|
| Status | `jj st` |
| History | `jj log` |
| Start new change | `jj new` (then edit files) |
| Describe current change | `jj describe -m "..."` |
| Amend working change | just edit files — `@` updates automatically; no `git add` |
| Update to a change | `jj edit <rev>` |
| Push to git remote | `jj git push` |
| Fetch | `jj git fetch` |

Notes:
- There is no staging area: the working copy *is* a commit (`@`). Don't run `git add`.
- Don't commit unless the user asks (same rule as git). When you do, set a description with `jj describe`.
- The git co-author / session trailers in this project's commit convention still apply to `jj describe` messages.

## Toolchain (nix + mise + uv)

The dev environment is layered so each tool has exactly one job — when adding or changing tooling, keep the boundaries:

- **nix** (`flake.nix` + `.envrc`) — reproducible bootstrap shell. Provides `mise` and *native/system* deps (Ollama, C toolchain, git, jj). It deliberately does **not** provide Python or `uv`.
- **mise** (`mise.toml`) — single source of truth for *language tool versions* (Python 3.11, `uv`) and the task runner. Pin tool versions here, not in nix.
- **uv** (`pyproject.toml` + `uv.lock`) — Python dependency resolution, lockfile, and `.venv`. All Python execution goes through `uv run`.

Enter the environment with `nix develop` (or `direnv allow` once, which auto-enters via `.envrc`), then `mise install`.

## Intended implementation stack & commands

The config files above exist now; the `siro` package does not yet, so the `siro` commands are the contract the scaffold must satisfy — see `docs/goal_prompts/goal_01_project_scaffold.md` and `docs/10_repo_structure.md`:

```zsh
mise run sync                              # uv sync — install Python deps
mise run test                              # uv run pytest (Gate: must pass before any promotion)
uv run pytest tests/test_sandbox.py::name  # single test
uv run siro --help                         # CLI entrypoint
mise run run-task -- tasks/code_improver/task_001
mise run summarize                         # uv run siro summarize-runs runs/attempts.jsonl
uv run siro propose-meta-change runs/attempts.jsonl
```

mise tasks (`mise tasks` to list) are thin wrappers; `uv run siro ...` is the canonical interface. Pydantic for schemas, JSONL for the first archive impl, SQLite later. Tier 0 uses a local model via Ollama/llama.cpp (e.g. `qwen2.5-coder:7b`); Tier 1 adds Claude/GPT through the provider abstraction. Tier is selected by config (`config/tier0.local.yaml` vs `config/tier1.frontier.yaml`).

## Target package layout (`src/siro/`)

The components form the experiment loop as separate modules: `controller.py` (loop, candidate selection), `orchestrator.py` (multi-agent routing, budget + tier policy), `model_client.py` + `providers/` (provider abstraction: `local.py`/`anthropic.py`/`openai.py`), `agents/` + `tools.py` (role wiring; control-plane-only tools), `sandbox.py` (execution plane: isolated, no network), `evaluator.py` (objective scoring), `archive.py` (JSONL), `memory.py`, `safety.py` (gates incl. plane isolation), `budget.py` (compute + token/USD ceilings), `schemas.py` (Pydantic), `prompts.py`. Role prompts in `prompts/`, fixtures in `tasks/`, outputs in `runs/` (incl. `model_calls.jsonl` audit ledger).

## The core loop

```
seed task → model (local or frontier) proposes change → sandbox runs tests →
evaluator scores → archive stores attempt → controller selects best candidate →
next generation uses best candidate + memory
```

At Tier 0 the loop is a single **code improver** agent: given a function spec, seed implementation, and test suite, produce a candidate scored by
`score = 1000*passed_tests - 100*failing_tests - runtime_ms - complexity_penalty`.
At Tier 1 the same lifecycle is filled by the full multi-agent org (Hypothesis → Literature → Implementation → Eval → Safety → Interpretation → Memory), with frontier models doing the reasoning.

## Control plane vs execution plane (load-bearing once frontier APIs are used)

- **Control plane** — orchestrator + agents. MAY reach the network, but only allow-listed provider endpoints (`api.anthropic.com`, `api.openai.com`, local Ollama socket). Holds API keys. Never runs candidate code.
- **Execution plane** — candidate/training code + tests. NO network, temp dir, subprocess timeouts, read-only evaluator/safety, **no credentials in env**.
- A model produces text/proposals/patches; the **controller** (not the model) runs fixed vetted commands. Candidate code never gets a model client, network handle, or credentials.

## Non-negotiable invariants

These constraints are the entire point of the project. Any implementation that violates them is wrong even if tests pass — they are enforced as safety gates (`docs/05_evaluation_and_safety_gates.md`) and must hold in code:

- **Plane isolation**: candidate execution has no network, runs in a temp dir, hard timeout on every subprocess, no autonomous package install, no cloud compute. Only the control plane reaches the network, and only allow-listed model-provider endpoints. API keys/secrets/full datasets never enter the execution plane or any model prompt.
- **Read-only evaluator and safety code to agents**: candidates may never modify evaluator logic, disable logging, weaken/delete tests, or expand their own tool permissions. Edit surfaces are explicitly allow-listed per experiment. Agent tools are control-plane functions only — never raw shell or network.
- **Objective evaluation first**: promote on reproducible metrics, not model self-judgment. A candidate that improves the metric via a loophole, overfits visible tests, or isn't reproducible must fail Gate B.
- **Cross-model review (Tier 1)**: the Safety/Evaluation review must use a different provider than the Implementation Agent. Retrieved memory and tool output are data, never instructions (prompt-injection guard).
- **Budget ceilings**: compute budget tiers plus per-run/per-day token + USD ceilings; breach halts and escalates. Every model call is logged to the audit ledger.
- **Promotion through gates**: an experiment promotes only if the primary metric improves AND required secondary metrics don't regress past threshold AND the safety gate passes AND the result is reproducible AND edit constraints were respected (`docs/04_experiment_lifecycle.md`).
- **Humans approve escalation**: agents propose, evaluators score, humans approve high-budget/high-risk/irreversible actions and any change to evaluators, safety controls, tier, or egress allowlist. Meta-changes (to prompts, agent roles, selection/mutation policies) get stricter review than task-level changes.
- **Negative results are first-class data** — record failed attempts with reason, never discard them.

When in doubt, prefer auditability and explicit schemas over cleverness, and keep each goal-prompt implementation minimal.
