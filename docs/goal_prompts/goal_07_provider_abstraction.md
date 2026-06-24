# Goal Prompt 07 — Model Provider Abstraction

## Goal

Generalize the single `ModelClient` from Goal 02 into a provider-agnostic layer that supports local models (Ollama) **and** frontier lab models (Claude, GPT), with structured outputs, tool use, and full cost accounting — without changing the existing loop, evaluator, sandbox, or gates.

See `07_model_providers_and_tiers.md`.

## Requirements

Implement under `src/siro/providers/`:

```python
class ModelClient(Protocol):
    def complete(self, request: ModelRequest) -> ModelResponse: ...
    def run(self, messages: list[Message], tools: list[ToolSpec],
            response_schema: type[BaseModel] | None) -> ModelResponse: ...
```

Backends:

- `local.py` — Ollama / llama.cpp (refactor the existing Goal 02 client into this).
- `anthropic.py` — Claude via the Messages API, with tool use and structured output.
- `openai.py` — GPT via the Responses/Chat API, with tool use and structured output.

All three return a common `ModelResponse` carrying text/structured content, tool calls, and **usage** (input/output tokens, estimated cost, latency).

## Configuration

- Provider, model name, timeout, and `api_key_env` come from config (`providers` block); never hardcoded.
- A `tier` and `agent_models` map bind each role to a provider (see `07_model_providers_and_tiers.md`).
- API keys are read from the environment named by `api_key_env`, only in the control plane.

## Budget and audit

- Implement `budget.py`: per-run and per-day token / USD ceilings; the controller halts and escalates on breach.
- Every model call is appended to `runs/model_calls.jsonl`: provider, model, prompt hash, token counts, cost estimate, latency, and the experiment it served.

## Acceptance criteria

- `uv run pytest` passes, including `tests/test_providers.py`.
- The Goal 02 code-improver loop runs unchanged at `tier: 0` (local) and at `tier: 1` with a frontier provider, selected by config only.
- Frontier calls enforce structured output against a Pydantic schema.
- Token / USD ceilings are enforced; exceeding a ceiling halts the run and escalates.
- Every model call appears in `runs/model_calls.jsonl`.
- No API key is ever read or present in the execution-plane (sandbox) environment.

## Constraints

- Network access is limited to the configured provider endpoints (egress allowlist).
- Swapping providers must not require editing the controller, evaluator, sandbox, gates, or memory schema.
- Lowering `tier` back to 0 must work with no code change.
