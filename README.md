# Self-Improving Research Organization

This directory codifies a practical, bounded version of a **self-improving research organization**: a multi-agent system that can propose research hypotheses, implement experiments, evaluate results, preserve structured scientific memory, and improve its own research process under explicit safety and governance gates.

The design is inspired by several public research directions:

- Karpathy's `autoresearch`: an agent edits a training script, runs fixed-budget experiments, and optimizes validation bits-per-byte.
- Anthropic's public framing of recursive self-improvement: AI systems increasingly assisting in building future AI systems, with humans still needed for oversight, judgment, and governance.
- DeepMind's AlphaEvolve: evolutionary LLM-driven algorithm/code improvement with evaluator feedback.
- Sakana AI's AI Scientist: automated idea generation, implementation, experimentation, paper writing, and review.

This is **not** a blueprint for unrestricted autonomous model self-replication or uncontrolled frontier training. The intended implementation is a constrained local or lab-scale testbed with objective evaluators, sandboxing, audit logs, and human approval gates.

## Document map

| File | Purpose |
|---|---|
| `00_principles.md` | Core principles, assumptions, tiers, and non-goals. |
| `01_system_architecture.md` | End-to-end architecture; control plane vs execution plane. |
| `02_research_operating_model.md` | How research work flows through the organization. |
| `03_agent_roles.md` | Agent role definitions, interfaces, and model assignment. |
| `04_experiment_lifecycle.md` | Experiment states, promotion rules, and rollback. |
| `05_evaluation_and_safety_gates.md` | Capability, safety, regression, and governance gates. |
| `06_research_memory_schema.md` | Schema for structured scientific memory. |
| `07_model_providers_and_tiers.md` | Provider abstraction (local + Claude + GPT) and capability tiers. |
| `08_frontier_prototype_architecture.md` | Tier 1: the full org prototyped with frontier LLMs. |
| `09_local_testbed_architecture.md` | Tier 0: minimal local implementation with local models and code evaluators. |
| `10_repo_structure.md` | Suggested repository layout. |
| `11_risks_and_controls.md` | Main failure modes and controls (incl. frontier-provider risks). |
| `12_references.md` | Public references used to ground this draft. |

Goal prompts live in `goal_prompts/`: `01`–`06` build the local Tier 0 testbed; `07`–`09` generalize the model layer and stand up the Tier 1 frontier organization.

## Capability tiers

The same loop, gates, and memory run at every tier — only the models behind the agents and the governance around them change (`07_model_providers_and_tiers.md`):

- **Tier 0** — fully local and offline; validates the machinery.
- **Tier 1** — frontier LLMs (Claude / GPT) prototype the full research organization; network egress is allow-listed to model providers only, and candidate execution stays offline.
- **Tier 2** — governed scale-up; human-gated.

Lowering the tier is always config-only and safe.

## Development environment

The toolchain is layered: **nix** (`flake.nix`) provides a reproducible bootstrap shell with `mise` and native deps; **mise** (`mise.toml`) pins the Python/`uv` versions and runs tasks; **uv** manages Python dependencies. See `09_local_testbed_architecture.md`.

```zsh
nix develop        # or: direnv allow  (auto-enters via .envrc)
mise install       # python 3.11 + uv at pinned versions
mise run sync      # uv sync
mise run test      # uv run pytest
mise tasks         # list available tasks
```

## Suggested use

1. Create a new repo.
2. Copy this directory into `docs/self-improving-research-org/`.
3. Start with `goal_prompts/goal_01_project_scaffold.md`.
4. Implement only the local, bounded testbed first.
5. Add autonomy only after evaluation, sandboxing, and auditability are working.
