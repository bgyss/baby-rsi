"""Goal 08 — the frontier organization runs the full cycle end-to-end, fully offline.

Every test drives the org with scripted clients (no network, no server, no credentials),
simulating distinct providers to exercise the cross-model-review invariant.
"""

from __future__ import annotations

import json

import pytest

from siro.agents.roles import MODEL_ROLES, build_agent
from siro.archive import JSONLArchive, ModelCallLedger
from siro.budget import BudgetExceeded, BudgetLimits, BudgetTracker
from siro.config import load_config
from siro.memory import ResearchMemory
from siro.model_client import ScriptedModelClient
from siro.orchestrator import Orchestrator
from siro.providers.base import ModelResponse, Usage
from siro.schemas import AttemptStatus, GateDecision

TASK = "tasks/code_improver/task_001"
GOOD_CODE = "def sum_list(values):\n    return sum(values)\n"
# Correct but strictly *more* complex than the seed: passes every test, yet is no
# objective improvement (more AST nodes, same test outcome) — so it must be rejected.
BLOATED_CODE = (
    "def sum_list(values):\n"
    "    total = 0\n"
    "    extra = 0\n"
    "    for v in values:\n"
    "        total = total + v\n"
    "    return total + extra\n"
)


def _responses(**overrides):
    """Canned JSON responses for each role; override any role's payload by name."""
    base = {
        "hypothesis": {
            "statement": "replace the manual loop with builtin sum()",
            "proposed_experiment": "rewrite sum_list using sum()",
            "required_metrics": ["pytest_pass_rate"],
            "predicted_result": "all tests pass, lower complexity",
            "expected_failure": "non-numeric inputs",
        },
        "literature": {"novelty": "incremental", "is_duplicate": False, "prior_art": "builtin sum"},
        "implementation": {"code": GOOD_CODE, "implementation_notes": "use builtin"},
        "evaluation": {"pass_fail": True, "regression_report": "no regressions"},
        "safety": {"classification": "safe", "escalate": False},
        "interpretation": {"result_summary": "works", "confidence": 0.9, "follow_up_experiments": ["try generators"]},
        "memory": {"strategy": "builtin-sum", "lessons_learned": ["prefer builtins"], "retrieval_tags": ["sum"], "follow_up": "explore generators"},
        "meta_research": {"proposed_change": "surface more lessons", "target": "retrieval_limit", "rollback_plan": "revert limit"},
    }
    base.update(overrides)
    return {role: json.dumps(payload) for role, payload in base.items()}


def _org(tmp_path, *, responses=None, require_cross_model=True, safety_provider="openai"):
    responses = responses or _responses()
    mem = ResearchMemory(tmp_path / "memory.jsonl")
    agents = {}
    for role in MODEL_ROLES:
        provider = safety_provider if role == "safety" else "anthropic"
        client = ScriptedModelClient([responses[role]], provider=provider, model=provider)
        agents[role] = build_agent(
            role,
            client,
            memory=mem,
            task_id="task_001",
            allowed_surfaces=[f"{TASK}/seed_solution.py"],
        )
    orch = Orchestrator(
        agents,
        memory=mem,
        archive=JSONLArchive(tmp_path / "attempts.jsonl"),
        ledger=ModelCallLedger(tmp_path / "model_calls.jsonl"),
        require_cross_model=require_cross_model,
    )
    return orch, mem


# --- the full cycle ---------------------------------------------------------


def test_full_cycle_completes_and_promotes(tmp_path):
    orch, mem = _org(tmp_path)
    result = orch.run_cycle("Make sum_list simpler and faster", TASK)

    assert result.promotion_decision is GateDecision.PASSED
    assert result.promoted
    assert result.attempt.status is AttemptStatus.PROMOTED
    # Every model-backed role ran and produced a validated structured output.
    assert set(result.agent_outputs) == set(MODEL_ROLES)
    assert result.next_actions == ["try generators"]


def test_every_model_call_is_in_the_audit_ledger(tmp_path):
    orch, _ = _org(tmp_path)
    orch.run_cycle("obj", TASK)
    rows = ModelCallLedger(tmp_path / "model_calls.jsonl").read_all()
    assert len(rows) == len(MODEL_ROLES)  # one per agent, all logged
    assert {r.provider for r in rows} == {"anthropic", "openai"}


def test_memory_record_written_through_curator(tmp_path):
    orch, mem = _org(tmp_path)
    orch.run_cycle("obj", TASK)
    entries = mem.all_entries()
    assert len(entries) == 1
    assert entries[0].strategy == "builtin-sum"  # curator field overlaid on the typed entry
    assert entries[0].follow_up == "explore generators"


def test_attempt_archived(tmp_path):
    orch, _ = _org(tmp_path)
    orch.run_cycle("obj", TASK)
    attempts = JSONLArchive(tmp_path / "attempts.jsonl").read_all()
    assert len(attempts) == 1


# --- cross-model review -----------------------------------------------------


def test_cross_model_review_provider_differs(tmp_path):
    orch, _ = _org(tmp_path)
    result = orch.run_cycle("obj", TASK)
    assert result.cross_model_review is True


def test_same_provider_safety_is_refused_when_required(tmp_path):
    orch, _ = _org(tmp_path, safety_provider="anthropic", require_cross_model=True)
    with pytest.raises(ValueError, match="Cross-model review"):
        orch.run_cycle("obj", TASK)


def test_safety_disagreement_escalates_instead_of_promoting(tmp_path):
    responses = _responses(safety={"classification": "unsafe", "escalate": True})
    orch, _ = _org(tmp_path, responses=responses)
    result = orch.run_cycle("obj", TASK)
    assert result.promotion_decision is GateDecision.ESCALATED
    assert not result.promoted
    assert any("cross-model disagreement" in e for e in result.escalations)
    # A gate-passing-but-escalated candidate is not promoted (objective gate still recorded).
    assert result.gates.passed
    assert result.attempt.status is AttemptStatus.REJECTED


def test_eval_agent_disagreement_is_surfaced(tmp_path):
    # Objective metrics pass, but the eval agent claims fail -> disagreement escalation.
    responses = _responses(evaluation={"pass_fail": False, "regression_report": "claims fail"})
    orch, _ = _org(tmp_path, responses=responses)
    result = orch.run_cycle("obj", TASK)
    assert any("disagrees with objective metrics" in e for e in result.escalations)


# --- triage + objective-first rejection -------------------------------------


def test_duplicate_is_triaged_out_before_execution(tmp_path):
    responses = _responses(literature={"novelty": "duplicate", "is_duplicate": True})
    orch, _ = _org(tmp_path, responses=responses)
    result = orch.run_cycle("obj", TASK)
    assert result.triaged_in is False
    assert result.promotion_decision is GateDecision.FAILED
    assert result.attempt.evaluation is None  # never executed


def test_non_improving_candidate_is_rejected(tmp_path):
    # Correct but more complex than the seed -> no objective improvement -> rejected.
    responses = _responses(implementation={"code": BLOATED_CODE})
    orch, _ = _org(tmp_path, responses=responses)
    result = orch.run_cycle("obj", TASK)
    assert result.promotion_decision is GateDecision.FAILED
    assert "no improvement" in result.attempt.reason


def test_static_gate_failure_blocks_execution(tmp_path):
    # A patch that opens a socket fails the static safety gate before any sandbox run.
    bad = "import socket\n\ndef sum_list(values):\n    return sum(values)\n"
    responses = _responses(implementation={"code": bad})
    orch, _ = _org(tmp_path, responses=responses)
    result = orch.run_cycle("obj", TASK)
    assert result.promotion_decision is GateDecision.FAILED
    assert result.attempt.status is AttemptStatus.REJECTED
    assert "gate" in result.attempt.reason


def test_out_of_bounds_meta_proposal_is_recorded_not_applied(tmp_path):
    responses = _responses(
        meta_research={
            "proposed_change": "raise the per-day USD budget ceiling",
            "target": "budget",
            "rollback_plan": "lower it back",
        }
    )
    orch, _ = _org(tmp_path, responses=responses)
    result = orch.run_cycle("obj", TASK)
    assert any("out of bounds" in e for e in result.escalations)


# --- budget enforcement -----------------------------------------------------


class _CostedClient:
    """A minimal client that reports a fixed per-call cost (to trip a budget ceiling)."""

    def __init__(self, text, *, provider, cost_usd):
        self._text = text
        self.provider = provider
        self.model = provider
        self.last_usage = Usage(input_tokens=100, output_tokens=100, cost_usd=cost_usd)

    def run(self, messages, tools=None, response_schema=None):  # noqa: ARG002
        return ModelResponse(
            text=self._text, provider=self.provider, model=self.model, usage=self.last_usage
        )


def test_budget_ceiling_halts_and_escalates(tmp_path):
    responses = _responses()
    mem = ResearchMemory(tmp_path / "memory.jsonl")
    ledger = ModelCallLedger(tmp_path / "model_calls.jsonl")
    agents = {}
    for role in MODEL_ROLES:
        provider = "openai" if role == "safety" else "anthropic"
        agents[role] = build_agent(
            role,
            _CostedClient(responses[role], provider=provider, cost_usd=1.0),
            memory=mem,
            task_id="task_001",
            allowed_surfaces=[f"{TASK}/seed_solution.py"],
        )
    # Ceiling of $0.50/run trips on the first agent call (each costs $1.00).
    budget = BudgetTracker(BudgetLimits(max_usd_per_run=0.5), ledger=ledger)
    orch = Orchestrator(
        agents,
        memory=mem,
        archive=JSONLArchive(tmp_path / "attempts.jsonl"),
        ledger=ledger,
        budget=budget,
        require_cross_model=True,
    )
    with pytest.raises(BudgetExceeded):
        orch.run_cycle("obj", TASK)
    # The call that tripped the ceiling was still logged — every call stays auditable.
    assert len(ledger.read_all()) == 1


# --- tier is config-only (tier 1 -> tier 0 with no code change) -------------


def test_from_config_tier0_requires_no_cross_model(tmp_path):
    config = load_config("config/tier0.local.yaml")
    orch = Orchestrator.from_config(
        config,
        memory=ResearchMemory(tmp_path / "m.jsonl"),
        archive=JSONLArchive(tmp_path / "a.jsonl"),
        ledger=ModelCallLedger(tmp_path / "l.jsonl"),
    )
    assert orch.require_cross_model is False  # all-local at Tier 0
    assert orch.budget_tier == 0


def test_from_config_tier1_binds_cross_model_by_config(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ak")
    monkeypatch.setenv("OPENAI_API_KEY", "ok")
    config = load_config("config/tier1.frontier.yaml")
    orch = Orchestrator.from_config(config)
    assert orch.require_cross_model is True
    assert orch.budget_tier == 1


def test_from_config_tier1_same_provider_is_refused(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ak")
    config = load_config("config/tier1.frontier.yaml")
    config.agent_models["safety"] = "anthropic"  # collide with implementation
    with pytest.raises(ValueError, match="Cross-model review"):
        Orchestrator.from_config(config)
