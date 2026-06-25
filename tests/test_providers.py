"""Goal 07 — the provider abstraction: local + Claude + GPT behind one interface.

Every test runs fully offline by injecting a fake ``transport`` (no network, no SDK,
no credentials) — the same discipline the candidate sandbox enforces.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from siro.config import load_config
from siro.providers import (
    AnthropicClient,
    LocalOpenAIClient,
    Message,
    ModelClient,
    OpenAIClient,
    ProviderConfig,
    ToolSpec,
    build_client,
)
from siro.providers._http import assert_allowed
from siro.providers.pricing import Pricing

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


class _Result(BaseModel):
    answer: int
    note: str = ""


def _openai_transport(body):
    """Return a transport that records the request and replies with ``body``."""
    captured: dict = {}

    def transport(url, payload, headers, timeout):
        captured["url"] = url
        captured["payload"] = payload
        captured["headers"] = headers
        return body

    transport.captured = captured  # type: ignore[attr-defined]
    return transport


# --- the interface ----------------------------------------------------------


def test_all_clients_satisfy_protocol():
    clients = [
        LocalOpenAIClient(transport=lambda *a: {}),
        AnthropicClient(transport=lambda *a: {}),
        OpenAIClient(transport=lambda *a: {}),
    ]
    for client in clients:
        assert isinstance(client, ModelClient)
        assert hasattr(client, "complete") and hasattr(client, "run")


# --- local (OpenAI-compatible) ----------------------------------------------


def test_local_generate_parses_text_and_usage():
    body = {
        "choices": [{"message": {"content": "```python\ndef f():\n    return 1\n```"}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 5},
    }
    client = LocalOpenAIClient(transport=_openai_transport(body))
    out = client.generate("improve this")
    assert "def f()" in out
    assert client.last_usage.input_tokens == 12
    assert client.last_usage.output_tokens == 5
    assert client.last_usage.cost_usd == 0.0  # local inference is free
    assert client.provider == "local"


def test_local_estimates_tokens_when_usage_absent():
    body = {"choices": [{"message": {"content": "hello world answer"}}]}
    client = LocalOpenAIClient(transport=_openai_transport(body))
    client.generate("a longish prompt that should estimate to some tokens")
    assert client.last_usage.input_tokens > 0
    assert client.last_usage.output_tokens > 0


# --- OpenAI (GPT) structured output -----------------------------------------


def test_openai_structured_output_validates_schema():
    transport = _openai_transport(
        {
            "choices": [{"message": {"content": '{"answer": 42, "note": "ok"}'}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 8},
        }
    )
    client = OpenAIClient(model="gpt-5.4", api_key="sk-test", transport=transport)
    resp = client.run([Message(role="user", content="q")], response_schema=_Result)
    assert isinstance(resp.structured, _Result)
    assert resp.structured.answer == 42
    # The request carried a json_schema response_format built from the Pydantic model.
    assert transport.captured["payload"]["response_format"]["type"] == "json_schema"
    # Cost is non-zero for a frontier provider.
    assert resp.usage.cost_usd > 0
    assert transport.captured["headers"]["Authorization"] == "Bearer sk-test"


def test_openai_tool_calls_parsed():
    transport = _openai_transport(
        {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {"name": "search", "arguments": '{"q": "x"}'},
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3},
        }
    )
    client = OpenAIClient(api_key="sk", transport=transport)
    resp = client.run(
        [Message(role="user", content="find x")],
        tools=[ToolSpec(name="search", description="search the web")],
    )
    assert resp.tool_calls[0].name == "search"
    assert resp.tool_calls[0].arguments == {"q": "x"}
    assert transport.captured["payload"]["tools"][0]["function"]["name"] == "search"


# --- Anthropic (Claude) structured output via a forced tool -----------------


def test_anthropic_structured_output_via_forced_tool():
    transport = _openai_transport(
        {
            "content": [
                {
                    "type": "tool_use",
                    "name": "emit_structured_result",
                    "input": {"answer": 7, "note": "claude"},
                }
            ],
            "usage": {"input_tokens": 30, "output_tokens": 10},
        }
    )
    client = AnthropicClient(model="claude-opus-4-8", api_key="ak", transport=transport)
    resp = client.run(
        [Message(role="system", content="be terse"), Message(role="user", content="q")],
        response_schema=_Result,
    )
    assert isinstance(resp.structured, _Result)
    assert resp.structured.answer == 7
    payload = transport.captured["payload"]
    assert payload["tool_choice"] == {"type": "tool", "name": "emit_structured_result"}
    assert payload["system"] == "be terse"  # system pulled out of the message list
    assert resp.usage.input_tokens == 30 and resp.usage.cost_usd > 0
    assert transport.captured["headers"]["x-api-key"] == "ak"


def test_anthropic_text_and_tool_use():
    transport = _openai_transport(
        {
            "content": [
                {"type": "text", "text": "let me search"},
                {"type": "tool_use", "name": "search", "input": {"q": "y"}, "id": "tu_1"},
            ],
            "usage": {"input_tokens": 4, "output_tokens": 6},
        }
    )
    client = AnthropicClient(api_key="ak", transport=transport)
    resp = client.run(
        [Message(role="user", content="go")],
        tools=[ToolSpec(name="search", description="s")],
    )
    assert resp.text == "let me search"
    assert resp.tool_calls[0].name == "search"


# --- egress allowlist -------------------------------------------------------


def test_assert_allowed_blocks_unlisted_host():
    allow = ["api.anthropic.com", "127.0.0.1:2276"]
    assert_allowed("https://api.anthropic.com/v1/messages", allow)  # ok
    assert_allowed("http://127.0.0.1:2276/v1/chat/completions", allow)  # ok with port
    with pytest.raises(PermissionError):
        assert_allowed("https://evil.example.com/v1", allow)


def test_client_enforces_allowlist_before_calling():
    called = {"n": 0}

    def transport(url, payload, headers, timeout):
        called["n"] += 1
        return {"choices": [{"message": {"content": "x"}}]}

    client = OpenAIClient(
        api_key="sk",
        base_url="https://api.openai.com/v1",
        allowed_endpoints=["api.anthropic.com"],  # openai NOT allowed
        transport=transport,
    )
    with pytest.raises(PermissionError):
        client.generate("hi")
    assert called["n"] == 0  # blocked before any network call


# --- factory + config-driven selection --------------------------------------


def test_build_client_maps_backends():
    local = build_client(ProviderConfig(key="local", backend="llamacpp", name="m"))
    anth = build_client(
        ProviderConfig(key="anthropic", backend="anthropic", name="claude-opus-4-8")
    )
    gpt = build_client(ProviderConfig(key="openai", backend="openai", name="gpt-5.4"))
    assert isinstance(local, LocalOpenAIClient)
    assert isinstance(anth, AnthropicClient)
    assert isinstance(gpt, OpenAIClient)
    with pytest.raises(ValueError):
        build_client(ProviderConfig(key="x", backend="bogus", name="m"))


def test_tier0_config_binds_every_role_local():
    config = load_config(CONFIG_DIR / "tier0.local.yaml")
    assert config.tier == 0
    assert config.budget.unbounded  # no ceilings at Tier 0
    for role in ["implementation", "evaluation", "safety", "anything"]:
        assert isinstance(config.client_for_role(role), LocalOpenAIClient)


def test_tier1_config_binds_roles_to_frontier_by_config_only(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ak-control-plane")
    monkeypatch.setenv("OPENAI_API_KEY", "ok-control-plane")
    config = load_config(CONFIG_DIR / "tier1.frontier.yaml")
    assert config.tier == 1
    # Per-role capability binding, distinct providers for implementation vs safety.
    assert isinstance(config.client_for_role("implementation"), AnthropicClient)
    assert isinstance(config.client_for_role("safety"), OpenAIClient)
    assert isinstance(config.client_for_role("evaluation"), LocalOpenAIClient)
    # Budget ceilings come from config, not code.
    assert config.budget.max_usd_per_run == 5.0
    assert config.budget.max_tokens_per_call == 8000
    # The egress allowlist is parsed and passed to clients.
    assert "api.anthropic.com" in (config.allowed_endpoints or [])


# --- end-to-end: providers → audit ledger → budget halt ---------------------

GOOD_CODE = "def sum_list(values):\n    return sum(values)\n"
TASK_DIR = "tasks/code_improver/task_001"


def _priced_local_client(cost_per_call_tokens=(100, 100)):
    """A local client whose transport returns valid code + a usage block, priced > 0."""
    body = {
        "choices": [{"message": {"content": f"```python\n{GOOD_CODE}```"}}],
        "usage": {"prompt_tokens": cost_per_call_tokens[0], "completion_tokens": cost_per_call_tokens[1]},
    }
    return LocalOpenAIClient(
        pricing=Pricing(input_per_mtok=10.0, output_per_mtok=30.0),  # pretend-priced local
        transport=_openai_transport(body),
    )


def test_loop_records_tokens_and_cost_to_ledger(tmp_path):
    from siro.archive import JSONLArchive, ModelCallLedger
    from siro.controller import Controller
    from siro.memory import ResearchMemory

    ledger = ModelCallLedger(tmp_path / "model_calls.jsonl")
    controller = Controller(
        archive=JSONLArchive(tmp_path / "attempts.jsonl"),
        ledger=ledger,
        memory=ResearchMemory(tmp_path / "memory.jsonl"),
    )
    controller.run_task(TASK_DIR, model=_priced_local_client(), generations=3)

    rows = ledger.read_all()
    assert len(rows) == 3
    assert all(r.input_tokens == 100 and r.output_tokens == 100 for r in rows)
    assert all(r.cost_usd > 0 for r in rows)  # cost estimate recorded per call
    assert all(r.pricing_metadata["input_per_mtok"] == 10.0 for r in rows)
    assert all(r.pricing_metadata["source_type"] == "default" for r in rows)


def test_budget_ceiling_halts_and_escalates_the_loop(tmp_path):
    from siro.archive import JSONLArchive, ModelCallLedger
    from siro.budget import BudgetExceeded, BudgetLimits, BudgetTracker
    from siro.controller import Controller
    from siro.memory import ResearchMemory

    ledger = ModelCallLedger(tmp_path / "model_calls.jsonl")
    # Each call costs (100+100)/1e6 * rates = 0.004 USD; ceiling trips after the first.
    budget = BudgetTracker(BudgetLimits(max_usd_per_run=0.003), ledger=ledger)
    controller = Controller(
        archive=JSONLArchive(tmp_path / "attempts.jsonl"),
        ledger=ledger,
        memory=ResearchMemory(tmp_path / "memory.jsonl"),
        budget=budget,
    )
    with pytest.raises(BudgetExceeded):
        controller.run_task(TASK_DIR, model=_priced_local_client(), generations=5)
    # The call that tripped the ceiling was still logged — every call is auditable.
    assert len(ledger.read_all()) == 1


def test_pricing_override_and_resolution():
    assert Pricing.resolve("anthropic", "claude-opus-4-8").input_per_mtok == 5.0
    assert Pricing.resolve("local", "anything").cost_usd(1000, 1000) == 0.0
    over = Pricing.resolve("openai", "unknown", override=(2.0, 4.0))
    assert over.cost_usd(1_000_000, 1_000_000) == 6.0
