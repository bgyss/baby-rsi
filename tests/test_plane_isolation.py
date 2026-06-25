"""Plane-isolation invariants: offline by default, no creds leak (Goal 01), and the
Tier 1 organization keeps candidate execution offline while only the control plane
reaches allow-listed endpoints (Goal 08)."""

import json

import pytest

from siro.agents.roles import MODEL_ROLES, build_agent
from siro.archive import JSONLArchive, ModelCallLedger
from siro.memory import ResearchMemory
from siro.model_client import ScriptedModelClient
from siro.orchestrator import Orchestrator
from siro.providers._http import assert_allowed
from siro.safety import (
    assert_execution_plane_isolated,
    network_allowed,
    scrub_execution_env,
)
from siro.sandbox import Sandbox, SandboxConfig
from siro.tools import read_allowed_file_tool


def test_network_off_by_default(monkeypatch):
    monkeypatch.delenv("SIRO_ALLOW_NETWORK", raising=False)
    assert network_allowed() is False


def test_network_flag_respected(monkeypatch):
    monkeypatch.setenv("SIRO_ALLOW_NETWORK", "true")
    assert network_allowed() is True
    monkeypatch.setenv("SIRO_ALLOW_NETWORK", "false")
    assert network_allowed() is False


def test_credentials_scrubbed_from_execution_env():
    env = {"ANTHROPIC_API_KEY": "secret", "OPENAI_API_KEY": "secret", "PATH": "/usr/bin"}
    scrubbed = scrub_execution_env(env)
    assert "ANTHROPIC_API_KEY" not in scrubbed
    assert "OPENAI_API_KEY" not in scrubbed
    assert scrubbed["PATH"] == "/usr/bin"


def test_assert_isolation_raises_on_leaked_credentials():
    with pytest.raises(PermissionError):
        assert_execution_plane_isolated({"OPENAI_API_KEY": "leak"})


def test_sandbox_child_env_has_no_credentials(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
    sandbox = Sandbox(SandboxConfig())
    assert sandbox.config.network == "disabled"
    assert "ANTHROPIC_API_KEY" not in sandbox.child_env()


# --- Goal 08: the frontier organization preserves plane isolation -----------

TASK = "tasks/code_improver/task_001"
GOOD_CODE = "def sum_list(values):\n    return sum(values)\n"


def _org_responses():
    payloads = {
        "hypothesis": {"statement": "use builtin sum", "proposed_experiment": "sum()"},
        "literature": {"novelty": "novel", "is_duplicate": False},
        "implementation": {"code": GOOD_CODE},
        "evaluation": {"pass_fail": True},
        "safety": {"classification": "safe", "escalate": False},
        "interpretation": {"result_summary": "ok"},
        "memory": {"strategy": "sum"},
        "meta_research": {"proposed_change": "x", "target": "retrieval_limit", "rollback_plan": "y"},
    }
    return {role: json.dumps(p) for role, p in payloads.items()}


def _scripted_org(tmp_path):
    responses = _org_responses()
    mem = ResearchMemory(tmp_path / "memory.jsonl")
    agents = {}
    for role in MODEL_ROLES:
        provider = "openai" if role == "safety" else "anthropic"
        agents[role] = build_agent(
            role,
            ScriptedModelClient([responses[role]], provider=provider, model=provider),
            memory=mem,
            task_id="task_001",
            allowed_surfaces=[f"{TASK}/seed_solution.py"],
        )
    orch = Orchestrator(
        agents,
        memory=mem,
        archive=JSONLArchive(tmp_path / "attempts.jsonl"),
        ledger=ModelCallLedger(tmp_path / "model_calls.jsonl"),
        require_cross_model=True,
    )
    return orch


def test_org_sandbox_is_offline_and_credential_free(tmp_path, monkeypatch):
    """Candidate execution stays offline + credential-free even with keys in the env."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    orch = _scripted_org(tmp_path)
    assert orch.sandbox.config.network == "disabled"
    assert "ANTHROPIC_API_KEY" not in orch.sandbox.child_env()
    assert "OPENAI_API_KEY" not in orch.sandbox.child_env()
    # A full cycle runs the candidate without ever giving the execution plane a credential.
    result = orch.run_cycle("obj", TASK)
    assert result.attempt.evaluation is not None  # candidate actually executed, offline


def test_agent_tools_never_reach_shell_or_network(tmp_path):
    """Agents only get control-plane tools — none can open a socket or spawn a shell."""
    orch = _scripted_org(tmp_path)
    for role in MODEL_ROLES:
        names = orch._agents[role].toolbox.names()
        assert not (set(names) & {"shell", "exec", "bash", "fetch", "http", "socket"})
    # The available tools are exactly the sanctioned control-plane ones.
    allowed = {"read_allowed_file", "query_memory", "list_references", "propose_patch"}
    for role in MODEL_ROLES:
        assert set(orch._agents[role].toolbox.names()) <= allowed


def test_read_tool_cannot_escape_allowed_surfaces(tmp_path):
    """The file tool refuses absolute escapes and evaluator/test surfaces (no exfiltration)."""
    tool = read_allowed_file_tool([tmp_path / "ok.py"])
    assert "not an allowed edit surface" in tool.invoke({"path": "/etc/passwd"})


def test_control_plane_egress_is_allowlisted_only():
    """Only allow-listed provider hosts are reachable from the control plane (Goal 07/08)."""
    allow = ["api.anthropic.com", "api.openai.com", "127.0.0.1:2276"]
    assert_allowed("https://api.anthropic.com/v1/messages", allow)
    with pytest.raises(PermissionError):
        assert_allowed("https://evil.example.com/v1", allow)
