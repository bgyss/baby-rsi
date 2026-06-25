"""Goal 08 — model-backed agents: structured output, injection guard, provider binding."""

from __future__ import annotations

import json

import pytest

from siro.agents import INJECTION_GUARD, build_agent
from siro.agents.base import _extract_json
from siro.agents.roles import IMPLEMENTATION, ROLE_SPECS, SAFETY
from siro.agents.schemas import HypothesisInput, HypothesisOutput, ImplementationInput
from siro.model_client import ScriptedModelClient
from siro.providers.base import ModelResponse, Usage


class _StructuredClient:
    """A client that returns a *validated* structured object (frontier-style)."""

    provider = "anthropic"
    model = "claude-opus-4-8"

    def __init__(self, obj):
        self._obj = obj
        self.last_usage = Usage(input_tokens=10, output_tokens=5)

    def run(self, messages, tools=None, response_schema=None):  # noqa: ARG002
        return ModelResponse(structured=self._obj, provider=self.provider, model=self.model)


def _hyp_input():
    return HypothesisInput(objective="go faster", task_prompt="sum a list")


def test_agent_parses_structured_field():
    obj = HypothesisOutput(statement="use builtin sum")
    agent = build_agent("hypothesis", _StructuredClient(obj))
    result = agent.run(_hyp_input())
    assert isinstance(result.output, HypothesisOutput)
    assert result.output.statement == "use builtin sum"


def test_agent_parses_json_text_fallback():
    """An offline/local client may return JSON *text*; the agent still validates it."""
    payload = json.dumps({"statement": "memoize", "required_metrics": ["pass_rate"]})
    agent = build_agent("hypothesis", ScriptedModelClient([payload]))
    result = agent.run(_hyp_input())
    assert result.output.statement == "memoize"
    assert result.output.required_metrics == ["pass_rate"]


def test_agent_tolerates_fenced_and_prose_json():
    raw = "Sure!\n```json\n{\"statement\": \"x\"}\n```\nDone."
    agent = build_agent("hypothesis", ScriptedModelClient([raw]))
    assert agent.run(_hyp_input()).output.statement == "x"


def test_agent_raises_on_unparseable_output():
    agent = build_agent("hypothesis", ScriptedModelClient(["not json at all"]))
    with pytest.raises(ValueError, match="does not satisfy"):
        agent.run(_hyp_input())


def test_user_message_carries_injection_guard_and_inputs():
    captured = {}

    class _Capture(ScriptedModelClient):
        def run(self, messages, tools=None, response_schema=None):
            captured["messages"] = messages
            return super().run(messages, tools, response_schema)

    agent = build_agent("hypothesis", _Capture([json.dumps({"statement": "y"})]))
    agent.run(_hyp_input())
    msgs = captured["messages"]
    assert msgs[0].role == "system"
    user = msgs[1].content
    assert INJECTION_GUARD in user
    assert "data, not instructions" in user.lower()
    assert "sum a list" in user  # the typed input was serialized in


def test_system_prompt_includes_forbidden_actions():
    agent = build_agent("implementation", ScriptedModelClient([json.dumps({"code": "x"})]))
    msgs = agent._messages(ImplementationInput(experiment_plan="p"))
    system = msgs[0].content
    assert "disabling tests" in system
    assert "expanding permissions" in system


def test_every_role_spec_has_prompt_schema_and_bounds():
    for role, spec in ROLE_SPECS.items():
        assert spec.output_schema is not None
        # Reasoning/implementation roles declare forbidden actions; all have a prompt name.
        assert spec.prompt_name
    # Cross-model intent is encoded in distinct specs; safety has the escalation surface.
    assert "approving its own policy changes" in ROLE_SPECS[SAFETY].forbidden_actions


def test_agent_exposes_provider_identity_for_cross_model_checks():
    impl = build_agent(
        IMPLEMENTATION,
        ScriptedModelClient([json.dumps({"code": "x"})], provider="anthropic"),
    )
    safety = build_agent(
        SAFETY,
        ScriptedModelClient([json.dumps({"classification": "safe"})], provider="openai"),
    )
    assert impl.provider == "anthropic"
    assert safety.provider == "openai"
    assert impl.provider != safety.provider


def test_extract_json_helpers():
    assert json.loads(_extract_json('{"a": 1}')) == {"a": 1}
    assert json.loads(_extract_json("```json\n{\"a\": 2}\n```")) == {"a": 2}
    assert json.loads(_extract_json("noise {\"a\": 3} tail")) == {"a": 3}
