# 07 — Model Providers and Capability Tiers

## Why this layer exists

The research organization is **model-provider agnostic**. The same agent roles, lifecycle, gates, and memory schema run whether an agent is backed by a small local model or a frontier lab model. This lets the project start as a safe local testbed and grow into a full research organization prototyped with frontier LLMs (Claude, GPT) *without changing the loop's mechanics or safety contract*.

A single provider abstraction sits behind every agent:

```python
class ModelClient(Protocol):
    def complete(self, request: ModelRequest) -> ModelResponse: ...
    # structured/tool-using variant used by frontier agents:
    def run(self, messages: list[Message], tools: list[ToolSpec],
            response_schema: type[BaseModel] | None) -> ModelResponse: ...
```

Concrete backends:

| Provider | Backend | Typical use |
|---|---|---|
| `local` | Ollama / llama.cpp (Qwen Coder, DeepSeek Coder) | Tier 0 testbed, cheap high-volume mutation |
| `anthropic` | Claude (Messages API, tool use, structured output) | Hypothesis, implementation, interpretation, meta-research |
| `openai` | GPT (Responses/Chat API, tool use, structured output) | Cross-model diversity, adversarial review, second opinions |

Provider, model name, temperature, token budget, and timeout are **configuration, not code**. Agents declare a *capability requirement*; the controller binds it to a concrete model per the active tier (see `03_agent_roles.md` → model assignment).

## Capability tiers

A "tier" is a deployment posture, not a single model. Each tier widens capability *and* tightens governance.

### Tier 0 — Local bounded testbed

- All agents backed by local models.
- No external API calls anywhere in the system.
- Fully offline; the strongest safety posture.
- Purpose: validate the loop mechanics, evaluators, sandbox, archive, and gates on objective code tasks (`09_local_testbed_architecture.md`).

### Tier 1 — Frontier-LLM research organization prototype

- Agents backed by frontier models (Claude / GPT) via APIs, mixed with local models for high-volume steps.
- This is where the **full organization** is actually prototyped: real hypothesis generation, literature reasoning, multi-step implementation, interpretation, and meta-research become tractable because frontier models can do them.
- Network egress is allowed **only** from the control plane to allow-listed model-provider endpoints (see below). Candidate execution stays offline.
- Purpose: run the end-to-end research org on real research-shaped tasks (`08_frontier_prototype_architecture.md`).

### Tier 2 — Governed scale-up (aspirational)

- Larger compute, longer experiments, possibly model-training experiments.
- Every capability beyond Tier 1 requires an explicit human-approved governance gate.
- Out of scope for the initial build; documented so the architecture leaves room for it without redesign.

## Control plane vs execution plane

Introducing frontier APIs forces a hard separation that is now a **core invariant**:

```text
┌─────────────────────────── CONTROL PLANE ───────────────────────────┐
│ Orchestrator + agents (reasoning).                                   │
│ MAY reach the network, but ONLY allow-listed model-provider endpoints│
│ (api.anthropic.com, api.openai.com, local Ollama socket).            │
│ Holds API keys. Never executes untrusted candidate code.             │
└──────────────────────────────────────────────────────────────────────┘
                                  │ produces patches / commands
                                  ▼
┌────────────────────────── EXECUTION PLANE ──────────────────────────┐
│ Candidate code, tests, training scripts.                             │
│ NO network. Temp dir. Subprocess timeouts. No API keys in env.       │
│ Read-only evaluator + safety code. All diffs logged.                 │
└──────────────────────────────────────────────────────────────────────┘
```

Rules:

- A model produces *text, structured proposals, or patches* — never executes them. The controller runs fixed, vetted commands in the execution plane.
- API keys and provider credentials live only in the control plane and are **never** present in the execution-plane environment.
- The egress allowlist is a safety control: the only outbound network permitted is to configured model-provider endpoints. Everything else is denied by default.
- Candidate/training code never gets a model client, a network handle, or credentials.

## Cost, budget, and rate governance

Frontier APIs introduce spend and a new runaway-cost risk. Treat tokens and dollars as a first-class budget alongside compute time (`02_research_operating_model.md` budget tiers):

- Per-run and per-day **token and cost ceilings**, enforced by the controller; halt-and-escalate on breach.
- Per-agent model assignment so expensive models are used only where they earn their cost (e.g. cheap local model for mutation, frontier model for interpretation).
- Every model call is logged to the audit ledger: provider, model, prompt hash, token counts, cost estimate, latency, and the experiment it served.
- Caching of identical requests where safe, to avoid paying twice for deterministic calls.

## Provider configuration

Extend the example config (`10_repo_structure.md`) with a providers block and per-role bindings:

```yaml
providers:
  local:
    backend: ollama
    name: qwen2.5-coder:7b
    timeout_seconds: 120
  anthropic:
    backend: anthropic
    name: claude-opus-4-8        # frontier reasoning / implementation
    api_key_env: ANTHROPIC_API_KEY
    timeout_seconds: 120
  openai:
    backend: openai
    name: gpt-5.4
    api_key_env: OPENAI_API_KEY
    timeout_seconds: 120

tier: 1                          # 0 = local-only, 1 = frontier prototype

agent_models:                    # capability binding per role
  hypothesis: anthropic
  literature: anthropic
  implementation: anthropic
  evaluation: local              # objective; model only summarizes
  safety: openai                 # cross-model reviewer, distinct from implementer
  interpretation: anthropic
  meta_research: anthropic

budget:
  max_usd_per_run: 5.00
  max_usd_per_day: 50.00
  max_tokens_per_call: 8000

network:
  egress: allowlist
  allowed_endpoints:
    - api.anthropic.com
    - api.openai.com
    - 127.0.0.1                  # local model server
```

## Provider-agnostic guarantees

Regardless of provider or tier, the following always hold:

- Objective evaluators — not model self-judgment — decide promotion.
- The safety agent that reviews a change should not be the same model instance that produced it; cross-model review is preferred at Tier 1.
- Swapping a provider must not require touching the controller, evaluator, sandbox, gates, or memory schema.
- Lowering the tier (e.g. 1 → 0) must always be safe and never require code changes — only config.
