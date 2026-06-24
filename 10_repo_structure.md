# 10 — Suggested Repository Structure

```text
self-improving-research-org/
  README.md
  flake.nix            # nix: reproducible bootstrap shell (mise + native deps)
  .envrc               # direnv: `use flake` + mise activation
  mise.toml            # mise: pinned python/uv versions + task runner
  pyproject.toml       # uv: Python project + dependencies
  uv.lock              # uv: resolved lockfile (checked in)
  config/
    tier0.local.yaml   # local-only config (Tier 0)
    tier1.frontier.yaml# frontier prototype config (Tier 1)
  docs/
    self-improving-research-org/
      00_principles.md
      01_system_architecture.md
      02_research_operating_model.md
      03_agent_roles.md
      04_experiment_lifecycle.md
      05_evaluation_and_safety_gates.md
      06_research_memory_schema.md
      07_model_providers_and_tiers.md
      08_frontier_prototype_architecture.md
      09_local_testbed_architecture.md
      10_repo_structure.md
      11_risks_and_controls.md
      12_references.md
      goal_prompts/
        goal_01_project_scaffold.md
        goal_02_code_improver_loop.md
        goal_03_research_memory.md
        goal_04_eval_and_safety_gates.md
        goal_05_meta_research_loop.md
        goal_06_local_training_autoresearch.md
        goal_07_provider_abstraction.md
        goal_08_frontier_research_org.md
        goal_09_research_task_suite.md
  src/
    siro/
      __init__.py
      controller.py
      orchestrator.py      # multi-agent routing, budget + tier policy (control plane)
      schemas.py
      model_client.py      # provider abstraction (Protocol)
      providers/
        __init__.py
        local.py           # Ollama / llama.cpp
        anthropic.py       # Claude
        openai.py          # GPT
      agents/
        __init__.py        # role wiring: prompt + output schema + tools per role
      tools.py             # control-plane tools agents may call (no shell/network)
      sandbox.py           # execution plane: no network, timeouts, temp dir
      evaluator.py
      archive.py
      memory.py
      safety.py            # gates incl. plane-isolation + provider integrity
      budget.py            # compute + token/USD accounting and ceilings
      prompts.py
  tasks/
    code_improver/
      task_001/
        prompt.md
        seed_solution.py
        tests.py
    research/             # Tier 1 research-shaped tasks
      research_001/
        brief.md
        baseline/
        eval.py
  prompts/
    orchestrator.md
    hypothesis_agent.md
    literature_agent.md
    implementation_agent.md
    evaluation_agent.md
    safety_agent.md
    interpretation_agent.md
    meta_research_agent.md
  runs/
    attempts.jsonl
    experiments.sqlite
    model_calls.jsonl    # audit ledger: provider, model, tokens, cost, latency
    artifacts/
  tests/
    test_controller.py
    test_sandbox.py
    test_evaluator.py
    test_archive.py
    test_providers.py
    test_plane_isolation.py
```

## Package goals

The repository should support entering a reproducible shell and driving the loop
through mise tasks (which wrap `uv run`):

```zsh
nix develop                          # or `direnv allow` once, then auto-enter
mise install                         # python + uv at pinned versions
mise run sync                        # uv sync

mise run run-task -- tasks/code_improver/task_001
mise run summarize
uv run siro propose-meta-change runs/attempts.jsonl
```

The underlying `uv run siro ...` commands remain the canonical interface; mise
tasks are thin, discoverable wrappers (`mise tasks`).

## Configuration

Ship checked-in example configs per tier. `tier0.local.yaml` is the offline default; `tier1.frontier.yaml` adds the providers / budget / egress blocks documented in `07_model_providers_and_tiers.md`. Selecting a tier is config-only — never a code change.

`config/tier0.local.yaml`:

```yaml
tier: 0

providers:
  local:
    backend: ollama
    name: qwen2.5-coder:7b
    timeout_seconds: 120

agent_models:        # every role local at Tier 0
  default: local

sandbox:
  timeout_seconds: 10
  network: disabled       # execution plane is always offline
  max_attempts_per_task: 20

evaluation:
  primary_metric: pytest_pass_rate
  require_reproducibility: true

safety:
  allow_network: false    # control-plane egress; off at Tier 0
  allow_package_install: false
  allow_evaluator_edits: false
```

For `tier1.frontier.yaml`, keep the `sandbox` and `safety.allow_evaluator_edits`/`allow_package_install` blocks identical, set `tier: 1`, add the `providers` (anthropic/openai), `agent_models` per-role bindings, `budget` (token/USD ceilings), and `network.egress: allowlist` blocks from `07_model_providers_and_tiers.md`. The execution-plane `sandbox.network` stays `disabled` at every tier.
