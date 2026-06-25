"""Goal 10 — the governance gate enforces the Tier 2 human-approval workflow.

Default-deny, content-hash binding, expiry/revocation, no self-approval, and config-only
tier behavior — all exercised offline against the append-only approvals ledger.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from siro.config import load_config
from siro.governance import (
    ApprovalLedger,
    GovernanceDenied,
    GovernanceGate,
    governed_action_hash,
)
from siro.schemas import ApprovalScope, GovernedAction, _utcnow


def _gate(tmp_path):
    return GovernanceGate(ApprovalLedger(tmp_path / "approvals.jsonl"))


# --- default-deny -----------------------------------------------------------


def test_governed_action_is_denied_without_approval(tmp_path):
    gate = _gate(tmp_path)
    with pytest.raises(GovernanceDenied) as exc:
        gate.require(
            GovernedAction.BUDGET_INCREASE,
            "max_usd_per_run",
            actor="meta-loop",
            rationale="needs more budget",
            payload={"max_usd_per_run": 20.0},
        )
    # The denial records a pending request (an auditable escalation), not nothing.
    assert exc.value.request.action is GovernedAction.BUDGET_INCREASE
    assert gate.status_of(exc.value.request.request_id) == "pending"
    assert len(gate.ledger.requests()) == 1


def test_approved_action_authorizes_then_is_consumed_when_single_use(tmp_path):
    gate = _gate(tmp_path)
    payload = {"max_usd_per_run": 20.0}
    # 1. request -> 2. human approves -> 3. require now authorizes.
    with pytest.raises(GovernanceDenied) as exc:
        gate.require(GovernedAction.BUDGET_INCREASE, "max_usd_per_run", payload=payload)
    gate.approve(exc.value.request.request_id, by="alice")

    decision = gate.require(GovernedAction.BUDGET_INCREASE, "max_usd_per_run", payload=payload)
    assert decision.granted and decision.approver == "alice"
    # Single-use: a second attempt is denied again (the approval was consumed).
    with pytest.raises(GovernanceDenied):
        gate.require(GovernedAction.BUDGET_INCREASE, "max_usd_per_run", payload=payload)


def test_standing_scope_authorizes_repeatedly(tmp_path):
    gate = _gate(tmp_path)
    payload = {"tier": 2}
    req = gate.request(GovernedAction.TIER_CHANGE, "tier", payload=payload, scope=ApprovalScope.STANDING)
    gate.approve(req.request_id, by="alice", scope=ApprovalScope.STANDING)
    assert gate.authorize(GovernedAction.TIER_CHANGE, "tier", payload=payload, consume=True) is not None
    # Still valid on a second use (standing, not consumed).
    assert gate.authorize(GovernedAction.TIER_CHANGE, "tier", payload=payload, consume=True) is not None


# --- hash binding -----------------------------------------------------------


def test_approval_is_bound_to_exact_change(tmp_path):
    gate = _gate(tmp_path)
    req = gate.request(GovernedAction.BUDGET_INCREASE, "max_usd_per_run", payload={"max_usd_per_run": 20.0})
    gate.approve(req.request_id, by="alice", scope=ApprovalScope.STANDING)
    # The approved change (20.0) authorizes; a different change (50.0) does not.
    assert gate.authorize(GovernedAction.BUDGET_INCREASE, "max_usd_per_run", payload={"max_usd_per_run": 20.0})
    assert gate.authorize(GovernedAction.BUDGET_INCREASE, "max_usd_per_run", payload={"max_usd_per_run": 50.0}) is None
    # A different action with the same payload also does not match.
    assert gate.authorize(GovernedAction.TIER_CHANGE, "max_usd_per_run", payload={"max_usd_per_run": 20.0}) is None


def test_hash_is_stable_and_change_sensitive():
    h1 = governed_action_hash(GovernedAction.BUDGET_INCREASE, "x", {"a": 1, "b": 2})
    h2 = governed_action_hash(GovernedAction.BUDGET_INCREASE, "x", {"b": 2, "a": 1})
    h3 = governed_action_hash(GovernedAction.BUDGET_INCREASE, "x", {"a": 1, "b": 3})
    assert h1 == h2  # key order does not matter
    assert h1 != h3  # a changed value does


# --- expiry + revocation ----------------------------------------------------


def test_expired_approval_does_not_authorize(tmp_path):
    gate = _gate(tmp_path)
    payload = {"max_usd_per_run": 20.0}
    req = gate.request(GovernedAction.BUDGET_INCREASE, "b", payload=payload, scope=ApprovalScope.STANDING)
    gate.approve(req.request_id, by="alice", expires_at=_utcnow() - timedelta(seconds=1))
    assert gate.authorize(GovernedAction.BUDGET_INCREASE, "b", payload=payload) is None
    assert gate.status_of(req.request_id) == "expired"


def test_revoked_approval_does_not_authorize(tmp_path):
    gate = _gate(tmp_path)
    payload = {"max_usd_per_run": 20.0}
    req = gate.request(GovernedAction.BUDGET_INCREASE, "b", payload=payload, scope=ApprovalScope.STANDING)
    decision = gate.approve(req.request_id, by="alice", scope=ApprovalScope.STANDING)
    assert gate.authorize(GovernedAction.BUDGET_INCREASE, "b", payload=payload) is not None
    gate.revoke(decision.decision_id, by="alice", reason="changed my mind")
    assert gate.authorize(GovernedAction.BUDGET_INCREASE, "b", payload=payload) is None
    assert gate.status_of(req.request_id) == "revoked"


def test_denied_request_does_not_authorize(tmp_path):
    gate = _gate(tmp_path)
    payload = {"max_usd_per_run": 20.0}
    req = gate.request(GovernedAction.BUDGET_INCREASE, "b", payload=payload)
    gate.deny(req.request_id, by="alice", reason="too risky")
    assert gate.authorize(GovernedAction.BUDGET_INCREASE, "b", payload=payload) is None
    assert gate.status_of(req.request_id) == "denied"


# --- no self-approval -------------------------------------------------------


def test_approval_requires_a_human_approver(tmp_path):
    gate = _gate(tmp_path)
    req = gate.request(GovernedAction.MODEL_DEPLOY, "role:implementation")
    with pytest.raises(ValueError, match="human"):
        gate.approve(req.request_id, by="")  # no approver id -> refused


def test_no_agent_tool_can_approve():
    # Structural: the control-plane toolset (every tool factory tools.py exports) has no
    # approval/governance tool. An agent can request (via the controller) but the grant path
    # lives only on the human-operated CLI / gate.
    import siro.tools as tools

    tool_factories = [n for n in tools.__all__ if n.endswith("_tool")]
    assert tool_factories  # sanity: there are tools
    assert not any("approv" in n or "govern" in n for n in tool_factories)


# --- tier is config-only ----------------------------------------------------


def test_gate_is_disabled_below_tier_2(tmp_path):
    cfg0 = load_config("config/tier0.local.yaml")
    cfg1 = load_config("config/tier1.frontier.yaml")
    assert GovernanceGate.from_config(cfg0).enabled is False
    assert GovernanceGate.from_config(cfg1).enabled is False


def test_gate_is_enabled_at_tier_2_by_config():
    cfg2 = load_config("config/tier2.governed.yaml")
    assert cfg2.tier == 2
    assert GovernanceGate.from_config(cfg2).enabled is True
