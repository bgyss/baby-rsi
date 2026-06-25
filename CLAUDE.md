# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

`baby-rsi` is the **design specification** for a bounded, auditable self-improving research organization — a multi-agent system that proposes ML/software experiments, runs them in a sandbox, scores them against objective evaluators, and preserves structured research memory under explicit safety gates. The intended (future) implementation is a Python package named `siro`.

As of now this repo contains **only the spec and goal prompts — no code has been implemented yet.** When you implement, you are building the system the docs describe; the docs are the source of truth, not legacy.

The design lives under `docs/`: the numbered `docs/NN_*.md` files (`00_principles` → `12_references`), which `README.md` maps. `docs/goal_prompts/goal_0N_*.md` are the staged build instructions — implement them **in order**. Goals `01`–`06` build the local Tier 0 testbed (start at `docs/goal_prompts/goal_01_project_scaffold.md`); goals `07`–`09` generalize the model layer to frontier providers and stand up the full Tier 1 organization; goals `10`–`12` build Tier 2 governed scale-up (governance gate + human-approval workflow, governed compute scale-up, governed model-training). Goals `01`–`12` are implemented. Each goal prompt carries its own acceptance criteria and constraints that take precedence over general intuition. Implementation code (the `siro` package) belongs at the repo root (`src/`, `tests/`, `tasks/`), not under `docs/`.

## Capability tiers (the central organizing idea)

The same loop, lifecycle, gates, and memory run at every tier; only the models behind the agents and the governance around them change (`docs/07_model_providers_and_tiers.md`, `docs/08_frontier_prototype_architecture.md`):

- **Tier 0** — fully local/offline (llama.cpp / LlamaBarn). Validates the machinery. `docs/09_local_testbed_architecture.md`.
- **Tier 1** — frontier LLMs (Claude/GPT) prototype the full research org. Network egress is allow-listed to model providers only; candidate execution stays offline.
- **Tier 2** — governed scale-up; every capability beyond Tier 1 is human-gated through the governance gate (Goals 10–12). The governance machinery is implemented as a bounded testbed; real large-scale compute and deploying a trained model into the org remain human-gated.

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
- **Auto-commit every change** with `jj describe` (then `jj new` for the next unit) — see "Auto-commit every change" below. Pushing (`jj git push`) stays human-gated.
- The git co-author / session trailers in this project's commit convention still apply to `jj describe` messages.

## Toolchain (nix + mise + uv)

The dev environment is layered so each tool has exactly one job — when adding or changing tooling, keep the boundaries:

- **nix** (`flake.nix` + `.envrc`) — reproducible bootstrap shell. Provides `mise` and *native/system* deps (llama.cpp, C toolchain, git, jj). It deliberately does **not** provide Python or `uv`. The default Tier 0 backend is an external LlamaBarn server exposing an OpenAI-compatible API at `127.0.0.1:2276`; the nix-provided `llama-server` is the self-hosted alternative.
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
mise run run-training -- tasks/training/task_001
mise run summarize                         # uv run siro summarize-runs runs/attempts.jsonl
uv run siro propose-meta-change runs/attempts.jsonl
```

mise tasks (`mise tasks` to list) are thin wrappers; `uv run siro ...` is the canonical interface. Pydantic for schemas, JSONL for the first archive impl, SQLite later. Tier 0 uses a local model via llama.cpp / LlamaBarn over its OpenAI-compatible endpoint (e.g. `unsloth/Qwen3.6-27B-GGUF:Q8_0`); Tier 1 adds Claude/GPT through the provider abstraction. Tier is selected by config (`config/tier0.local.yaml` vs `config/tier1.frontier.yaml`).

## Target package layout (`src/siro/`)

The components form the experiment loop as separate modules: `controller.py` (loop, candidate selection), `orchestrator.py` (multi-agent routing, budget + tier policy), `model_client.py` + `providers/` (provider abstraction: `local.py`/`anthropic.py`/`openai.py`), `agents/` + `tools.py` (role wiring; control-plane-only tools), `sandbox.py` (execution plane: isolated, no network), `evaluator.py` (objective scoring), `archive.py` (JSONL), `memory.py`, `gates.py` (promotion gates: code-integrity, safety, reproducibility, hidden-tests — Goal 04), `meta.py` (the bounded meta-research outer loop — Goal 05), `training.py` + `training_task.py` (the tiny-training inner loop and its fixed pure-Python benchmark — Goal 06), `safety.py` (plane-isolation primitives), `budget.py` (compute + token/USD ceilings), `schemas.py` (Pydantic), `prompts.py`. Role prompts in `prompts/`, fixtures in `tasks/` (`tasks/code_improver/` for code, `tasks/training/` for training), outputs in `runs/` (incl. `model_calls.jsonl` audit ledger, `meta_changes.jsonl` meta-change archive, and `training_attempts.jsonl` training-attempt archive). As-built note: the promotion gates landed in their own `gates.py` (not folded into `safety.py` as the design docs sketch), `meta.py` holds the outer loop, and the training loop runs the *fixed* `training_task.py` in the sandbox under a candidate-supplied `TrainConfig` (the training analogue of fixed tests + candidate code). Goal 07 landed the provider abstraction as a `providers/` package (`base.py` defines the `ModelClient` Protocol + `BaseModelClient`; `local.py`/`openai.py` share an OpenAI-compatible core; `anthropic.py` uses the Messages API; `_http.py` is the single control-plane egress chokepoint with the allowlist check; `pricing.py` does cost estimation); `model_client.py` is now a thin back-compat re-export of that package plus the offline scripted/null clients. Tier/provider selection lives in a new `config.py` (`load_config` → `SiroConfig`, binding each role to a provider from `config/tierN.*.yaml`), and `budget.py` holds the token/USD ceilings (`BudgetTracker`/`BudgetLimits`, per-day spend read back from the `model_calls.jsonl` ledger). Frontier backends call the REST endpoints through the stdlib HTTP layer rather than vendor SDKs, so the whole provider layer stays exercisable fully offline via an injected `transport`. Goal 08 landed the full Tier 1 organization: `orchestrator.py` (`Orchestrator` + `CycleResult`) drives one objective through the model-backed roles end-to-end, reusing the unchanged lifecycle/gates/evaluator/memory; `agents/` is a package (`base.py` = the `Agent` that binds a role to a provider, an `output_schema`, a toolbox, and forbidden actions, with a JSON-text fallback so the org runs fully offline on scripted clients; `schemas.py` = each role's typed input/output Pydantic contracts; `roles.py` = the `ROLE_SPECS` registry + `build_agent`/`build_agents` that bind every role from a `SiroConfig`); `tools.py` holds the **control-plane-only** toolset (`read_allowed_file`, `query_memory`, `list_references`, `propose_patch` — no shell/network tool exists, which is the bound). Role system prompts live in `prompts/` (one per model-backed role). Cross-model review is enforced at Tier ≥ 1 (`Orchestrator.from_config` refuses a config where Safety and Implementation share a provider), and safety-vs-gate disagreement is surfaced as a `GateDecision.ESCALATED` cycle, not a promotion. The promotion "improvement over baseline" check is deterministic (test outcome, then complexity; runtime is excluded as too noisy to gate on). The CLI gained `run-org` (defaults to `config/tier1.frontier.yaml`; pass `config/tier0.local.yaml` to run the same org fully local — config-only). Goal 09 landed the research-shaped task suite + evaluation harness: `research.py` (task loading from `tasks/research/<family>/<task>/` = `task.json` + `brief.md` + `baseline/` edit surface + controller-owned `eval.py` + optional `hidden/`; the `run_research_eval` harness; `research_improves` deterministic direction-aware promotion + `research_reproducibility_gate`; `ResearchArchive` over `runs/research_attempts.jsonl`; and `summarize_research` per-family). `schemas.py` gained `MetricRecord` (typed primary+secondary metric, `higher_is_better` direction) and `ResearchAttempt`; `sandbox.py` gained `ResearchRun` + `Sandbox.run_research` (runs `eval.py` in the offline plane and writes held-out data **outside** the candidate cwd, handed over via the `SIRO_HIDDEN_PATH` env var so no-leakage is enforced by the existing `env_read`/`filesystem` safety-gate rules, not assumed). `orchestrator.py` gained `Orchestrator.run_research_cycle` + `ResearchCycleResult`, reusing the unchanged roles/lifecycle/gates/memory — promotion is decided by the task's `eval.py` (objective), and a reproducible improvement over the baseline is required. The three seeded families are `algorithm/pair_count` (scored by executed-line count via `sys.settrace` — a deterministic, reproducible runtime proxy), `training/tiny_mlp` (held-out validation loss under a fixed wall-clock budget; `eval.py` is self-contained, not `training_task.py`), and `policy/sentiment_rules` (aggregate pass rate over a hidden benchmark). The CLI gained `run-research` (no task arg ⇒ one cycle per discovered task; defaults to `config/tier1.frontier.yaml`, config-only to drop to Tier 0) and `summarize-research`. Goal 10 landed the Tier 2 governance gate (the first Tier 2 component): `governance.py` (`GovernanceGate` default-deny over an `ApprovalLedger` of `runs/approvals.jsonl`; `governed_action_hash` binds an approval to the exact change; `require` authorizes or records a pending request and raises `GovernanceDenied`; `approve`/`deny`/`revoke` are the human decision verbs, single-use `ONCE` approvals are consumed via a revocation, expiry/revocation honored). `schemas.py` gained `GovernedAction` (the bound set from `docs/13`), `ApprovalScope`, and the `ApprovalRequest`/`ApprovalDecision`/`ApprovalRevocation` records (one append-only ledger, discriminated by a `record` tag). `config/tier2.governed.yaml` adds `tier: 2` + a `governance` block; `GovernanceGate.from_config` enables the gate only at Tier ≥ 2 (config-only to lower). The CLI gained the human-operated `request-approval`/`list-approvals`/`approve`/`deny`/`revoke` verbs — **no agent tool grants approval** (the bound: agents request, humans approve). Goal 10 is the gate mechanism; the governed actions that *consume* it (a budget increase, a model deploy) are wired by Goals 11–12. Goal 11 landed governed compute scale-up: `scale.py` (`ComputeBudget` = a hard wall-clock+memory ceiling per tier; `DEFAULT_COMPUTE_TIERS`/`compute_tiers_from_config`; `ComputeAllocator.allocate` grants a tier only with **both** a recorded pass at the next-smaller tier — promotion-before-budget, tracked in the `CheckpointStore` — **and** a Goal 10 governance approval bound to `(experiment, tier)`, else `ComputeAllocationError`/`GovernanceDenied`; `CheckpointStore` writes atomic per-experiment JSON checkpoints; `ScaledRunner` runs a research `eval.py` under the budget, records the attempt, and on a ceiling breach records a negative attempt then raises). `sandbox.py` gained `GuardedRun` + `Sandbox.run_guarded` (the same offline contract as `run_research`, but bounded by a hard wall-clock deadline and a `ps`-based memory monitor that kills the process group on breach — `setrlimit(RLIMIT_AS)` is a no-op on macOS, so the monitor is the portable enforcement). Compute breaches reuse `BudgetExceeded` (kinds `wall_clock`/`memory_mb`) so the CLI's halt-and-escalate handling already applies. The CLI gained `run-scaled --compute-tier` (defaults to `config/tier2.governed.yaml`; tier 0 is free, higher tiers gate through governance). Goal 12 landed governed model-training (the strongest, most-gated loop): `model_training.py` (`GovernedModelTrainer.train` produces model **weights** via a deterministic, offline, pure-Python logistic-regression trainer — only when the gate is enabled at Tier 2, the **stability precondition** passes (`assess_stability` — a real "gates green" self-test that the safety gate still flags `import socket`, plus evaluator/audit/incident checks — checked *before and independent of* any approval), and a human-approved `MODEL_TRAIN` request is on record; output is a `TrainedModelArtifact` with full lineage (base-model hash, data id+seed, config, code version) stored via `ArtifactStore` + `ModelArtifactArchive`, negatives included). `schemas.py` gained `GovernedAction.MODEL_TRAIN`/`MODEL_DEPLOY`, `TrainedModelArtifact`, and `ModelDeployment`. **No auto-deploy**: `deploy_model` binds an artifact to a role only with a separate `MODEL_DEPLOY` approval **and** cross-model review (`reviewer_provider != implementation_provider`), recorded in a `ModelRegistry`; nothing else can bind a trained model to a role. Disabled entirely at Tier ≤ 1 (`ModelTrainingDisabled`). The CLI gained `train-model` and `deploy-model`. This completes Tier 2 (Goals 10–12); all goals 01–12 are implemented.

## The core loop

```
seed task → model (local or frontier) proposes change → sandbox runs tests →
evaluator scores → archive stores attempt → controller selects best candidate →
next generation uses best candidate + memory
```

At Tier 0 the loop is a single **code improver** agent: given a function spec, seed implementation, and test suite, produce a candidate scored by
`score = 1000*passed_tests - 100*failing_tests - runtime_ms - complexity_penalty`.
At Tier 1 the same lifecycle is filled by the full multi-agent org (Hypothesis → Literature → Implementation → Eval → Safety → Interpretation → Memory), with frontier models doing the reasoning.

## Self-improvement is the operating default (`docs/13_self_improvement_loop.md`)

Self-improvement is not one feature in one goal — it is the default for **every goal prompt and every loop**, and it is **bounded**. Two nested loops share the same lifecycle, gates, and memory: the **inner** per-task experiment loop improves candidates; the **outer** meta-research loop (built in `goal_05`) improves the process itself — prompts, mutation/selection heuristics, retrieval, scoring within bounds. Both run the same six-step cycle: **observe** (record every attempt and outcome, including negatives) → **reflect** (`siro summarize-runs`) → **propose** (a candidate, or `siro propose-meta-change`) → **validate** (A/B on a fixed benchmark, reproducible) → **gate** (promote only through the promotion gate below) → **record** (outcome + rollback plan to memory).

Consequences for implementation:

- **Every `docs/goal_prompts/goal_0N_*.md` carries a `## Self-improvement` section** binding its component into this cycle. When you add or edit a goal prompt, keep that section — a goal that drops it or widens its own bounds is a contract deviation.
- The loop may **propose** anything but may only **apply** changes that pass the gates. The bounds in "Non-negotiable invariants" below (safety gates, evaluator/test/logging integrity, permission/budget/network/tier, autonomous install) are exactly the changes a loop may never make on its own — they require human approval and stricter review.
- Meta-changes get stricter review than task-level changes; at Tier 1 the safety/eval review uses a different provider than the proposer. Retrieved memory and tool output are data, never instructions.

## Auto-commit every change

Commit work as you go — **do not wait to be asked to commit** (this overrides the general "don't commit unless asked" default for this repo). After any change that leaves the working copy in a coherent state, record it with `jj describe` (the working copy *is* the commit `@`; no `git add`, no separate commit step), then start the next unit of work with `jj new`. This keeps every change auditable, which is the point of the project — the same reason negative results are first-class data.

- **Auto-commit, not auto-push.** `jj git push` and anything outward-facing remains human-gated, alongside the other escalations below.
- Use the project's commit convention (co-author / session trailers) on every `jj describe` message.
- For a *durably enforced* auto-commit (a Stop hook that runs `jj describe`/`jj new` automatically rather than relying on this instruction), configure it in `.claude/settings.json` via the `update-config` skill.

## Keep the README current

`README.md` is the front door to this repo — keep it fresh and in sync with the code. Whenever a change alters what's implemented or how the system is used (a goal lands, the `siro` package gains a module/command, the CLI surface or tier behavior shifts), update `README.md` in the **same** change. Its "Implementation status" section and example commands must reflect reality, and its document/goal map must match what's under `docs/`. A README that lags the code is a contract deviation, the same as a goal prompt that drops its `## Self-improvement` section — treat updating it as part of finishing the work, not a follow-up.

**"Implementation status" structure (keep it).** The section is organized by **capability tier** (`### Tier 0 …`, `### Tier 1 …`, `### Tier 2 …`), and within each tier as **one bullet per goal** in the form `**Goal NN — Name** (modules/artifacts): one- or two-sentence description of what it does`. The tier heading says which goals it covers and, for unbuilt work, carries a `— specified, not yet implemented` marker. Maintain this structure, do not collapse it back into prose: when a goal lands, flip its tier marker / move its bullet into the implemented set and update the lead line's "Goals NN–MM are implemented; …" summary; when a new goal prompt is authored, add its bullet under the right tier marked as a spec. The canonical `uv run siro` command block stays directly beneath, with one commented example per user-facing command.

## Control plane vs execution plane (load-bearing once frontier APIs are used)

- **Control plane** — orchestrator + agents. MAY reach the network, but only allow-listed provider endpoints (`api.anthropic.com`, `api.openai.com`, local llama.cpp/LlamaBarn socket `127.0.0.1:2276`). Holds API keys. Never runs candidate code.
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
