"""Plane-isolation invariants hold at Goal 01: offline by default, no creds leak."""

import pytest

from siro.safety import (
    assert_execution_plane_isolated,
    network_allowed,
    scrub_execution_env,
)
from siro.sandbox import Sandbox, SandboxConfig


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
