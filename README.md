# Self-Improving Research Organization

This directory codifies a practical, bounded version of a **self-improving research organization**: a multi-agent system that can propose research hypotheses, implement experiments, evaluate results, preserve structured scientific memory, and improve its own research process under explicit safety and governance gates.

The design is inspired by several public research directions:

- Karpathy's `autoresearch`: an agent edits a training script, runs fixed-budget experiments, and optimizes validation bits-per-byte.
- Anthropic's public framing of recursive self-improvement: AI systems increasingly assisting in building future AI systems, with humans still needed for oversight, judgment, and governance.
- DeepMind's AlphaEvolve: evolutionary LLM-driven algorithm/code improvement with evaluator feedback.
- Sakana AI's AI Scientist: automated idea generation, implementation, experimentation, paper writing, and review.

This is **not** a blueprint for unrestricted autonomous model self-replication or uncontrolled frontier training. The intended implementation is a constrained local or lab-scale testbed with objective evaluators, sandboxing, audit logs, and human approval gates.

## Document map

All design docs live under [`docs/`](docs/).

| File | Purpose |
|---|---|
| `docs/00_principles.md` | Core principles, assumptions, tiers, and non-goals. |
| `docs/01_system_architecture.md` | End-to-end architecture; control plane vs execution plane. |
| `docs/02_research_operating_model.md` | How research work flows through the organization. |
| `docs/03_agent_roles.md` | Agent role definitions, interfaces, and model assignment. |
| `docs/04_experiment_lifecycle.md` | Experiment states, promotion rules, and rollback. |
| `docs/05_evaluation_and_safety_gates.md` | Capability, safety, regression, and governance gates. |
| `docs/06_research_memory_schema.md` | Schema for structured scientific memory. |
| `docs/07_model_providers_and_tiers.md` | Provider abstraction (local + Claude + GPT) and capability tiers. |
| `docs/08_frontier_prototype_architecture.md` | Tier 1: the full org prototyped with frontier LLMs. |
| `docs/09_local_testbed_architecture.md` | Tier 0: minimal local implementation with local models and code evaluators. |
| `docs/10_repo_structure.md` | Suggested repository layout. |
| `docs/11_risks_and_controls.md` | Main failure modes and controls (incl. frontier-provider risks). |
| `docs/12_references.md` | Public references used to ground this draft. |
| `docs/13_self_improvement_loop.md` | The uniform, bounded self-improvement contract every goal prompt and loop follows. |

Goal prompts live in `docs/goal_prompts/`: `01`–`06` build the local Tier 0 testbed; `07`–`09` generalize the model layer and stand up the Tier 1 frontier organization. Every goal prompt carries a `## Self-improvement` section that binds its component into the bounded self-improvement cycle defined in `docs/13_self_improvement_loop.md`.

## Capability tiers

The same loop, gates, and memory run at every tier — only the models behind the agents and the governance around them change (`docs/07_model_providers_and_tiers.md`):

- **Tier 0** — fully local and offline; validates the machinery.
- **Tier 1** — frontier LLMs (Claude / GPT) prototype the full research organization; network egress is allow-listed to model providers only, and candidate execution stays offline.
- **Tier 2** — governed scale-up; human-gated.

Lowering the tier is always config-only and safe.

## Development environment

The toolchain is layered: **nix** (`flake.nix`) provides a reproducible bootstrap shell with `mise` and native deps; **mise** (`mise.toml`) pins the Python/`uv` versions and runs tasks; **uv** manages Python dependencies. See `docs/09_local_testbed_architecture.md`.

```zsh
nix develop        # or: direnv allow  (auto-enters via .envrc)
mise install       # python 3.11 + uv at pinned versions
mise run sync      # uv sync
mise run test      # uv run pytest
mise tasks         # list available tasks
```

## Implementation status

Goals 01–09 are implemented: the `siro` package (`src/siro/`) with explicit Pydantic
schemas, an append-only JSONL archive + audit ledger, plane-isolation safety
primitives, the objective scoring function, and a CLI surface (Goal 01); the per-task
code-improver loop — `controller` + isolated `sandbox` execution (Goal 02); durable
research `memory` distilled into the proposer prompt (Goal 03); the promotion
`gates` — code-integrity, safety, reproducibility, and hidden-test gates that bound
what the loop may promote (Goal 04); the bounded meta-research outer loop — `meta`,
which reflects on the archive, proposes a reversible process change (prompts/retrieval),
A/B-tests it against the current process on a fixed benchmark, and recommends
promote/reject, with a separate `runs/meta_changes.jsonl` archive, a generated rollback
plan, and durable application held behind a human-approval flag (Goal 05); and the
tiny-training autoresearch loop — `training` + the fixed `training_task` benchmark (a
deterministic pure-Python MLP), which applies the same inner loop to *training*: a
candidate proposes a bounded `TrainConfig` delta, the sandbox trains it under a fixed
wall-clock budget, and the best reproducible *validation-loss* improvement is promoted,
with config deltas logged to a separate `runs/training_attempts.jsonl` archive (Goal 06);
and the provider abstraction — `providers/` (one `ModelClient` interface behind local
llama.cpp/LlamaBarn, Claude, and GPT backends, with structured output, tool use, and
per-call token/cost/latency accounting), `config` (tier and per-role provider binding
loaded from `config/tierN.*.yaml`), and `budget` (per-run/per-day USD and per-call token
ceilings that halt-and-escalate on breach) — so the same Goal 02 loop runs at Tier 0
(local) or Tier 1 (frontier) by **config only**, with every model call logged to
`runs/model_calls.jsonl` and no credential ever reaching the execution plane (Goal 07);
and the full Tier 1 research organization — `orchestrator` + `agents/` + `tools`, which
runs one human objective through the model-backed roles (Hypothesis → Literature → triage
→ Implementation → code-integrity/safety gates → offline sandbox → objective evaluator +
Evaluation narrative → cross-model Safety review → Interpretation → promotion gate → Memory
Curator → agenda update). Each role is a provider-bindable agent with a role system prompt
(`prompts/`), a typed input contract and Pydantic `output_schema` enforced via structured
output, and a constrained **control-plane-only** toolset (`read_allowed_file`,
`query_memory`, `list_references`, `propose_patch` — never shell or network). The same
lifecycle, gates, evaluator, and memory schema are reused unchanged; only the agents behind
the roles get more capable. The Safety reviewer binds to a *different* provider than the
Implementation Agent (required and verified at Tier ≥ 1), and a disagreement between the
safety reviewer and the objective promotion gate is surfaced as an **escalation**, not a
tie-break. Every agent call is in the audit ledger and charged against the token/USD
ceilings, candidate execution stays offline and sandboxed, meta-research stays proposal-only
and human-gated, and dropping `tier: 1` → `tier: 0` returns the whole org to fully-local
operation with no code change (Goal 08);
and the research-shaped task suite + evaluation harness — `research` + `tasks/research/`,
which gives the org *real work* beyond single-function repair: three task families
(`algorithm/` scored by executed-line count vs. a hidden workload, `training/` a
Karpathy-style tiny-MLP scored by held-out validation loss under a fixed wall-clock budget,
and `policy/` a rule-based sentiment policy scored by aggregate pass rate over a held-out
benchmark). Each task carries a `brief.md`, a `baseline/` edit surface, a controller-owned
objective `eval.py` (the authority for promotion, returning a typed `MetricRecord`), and an
optional `hidden/` held-out set. `Orchestrator.run_research_cycle` runs the **same** full
lifecycle and gates on these tasks; promotion is decided by the objective evaluator (never
model self-judgment) and requires a *reproducible* improvement over the baseline. No-leakage
is **enforced, not assumed**: held-out data is handed to `eval.py` outside the candidate's
working directory via `SIRO_HIDDEN_PATH`, so there is no relative file to open and reading
the env var or an absolute path from candidate code trips the static safety gate. Attempts
(successes and negative results) land in a separate `runs/research_attempts.jsonl`, and
`summarize-research` reports, per family, pass rate, median cycles to success, safety-gate
failures, token/USD spend, and strategy diversity (Goal 09).
The canonical interface is `uv run siro` (mise tasks are thin wrappers):

```zsh
uv run siro --help
uv run siro summarize-runs runs/attempts.jsonl        # reflect on the archive
uv run siro run-task tasks/code_improver/task_001     # per-task code inner loop (Goal 02), Tier 0
uv run siro run-task tasks/code_improver/task_001 --config config/tier1.frontier.yaml  # Tier 1 (Goal 07)
uv run siro run-training tasks/training/task_001      # per-task training inner loop (Goal 06)
uv run siro run-org tasks/code_improver/task_001 --objective "Make sum_list simpler"  # full Tier 1 org cycle (Goal 08)
uv run siro run-org tasks/code_improver/task_001 --config config/tier0.local.yaml     # same org, fully local — config-only
uv run siro run-research                              # org runs every research-suite task (Goal 09)
uv run siro run-research tasks/research/training/tiny_mlp --config config/tier0.local.yaml  # one family, fully local
uv run siro summarize-research                        # per-family suite summary (Goal 09)
uv run siro propose-meta-change runs/attempts.jsonl   # meta-research outer loop (Goal 05)
```

## Suggested use

1. Read `docs/00_principles.md` and `docs/01_system_architecture.md` for the design.
2. Start with `docs/goal_prompts/goal_01_project_scaffold.md` and implement goals in order.
3. Implement only the local, bounded Tier 0 testbed first.
4. Add the frontier-LLM Tier 1 organization (goals `07`–`09`) only after evaluation, sandboxing, and auditability are working.
