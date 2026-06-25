"""Goal 11 — governed compute scale-up: allocation, ceilings, checkpointing, isolation.

Exercised offline. Real subprocesses drive the hard wall-clock + memory ceilings; the
governance gate (Goal 10) gates any tier above the default.
"""

from __future__ import annotations

import json

import pytest

from siro.budget import BudgetExceeded
from siro.config import load_config
from siro.governance import ApprovalLedger, GovernanceDenied, GovernanceGate
from siro.research import ResearchArchive, load_research_task
from siro.scale import (
    BackendPolicy,
    BackendPolicyError,
    CheckpointStore,
    ComputeAllocationError,
    ComputeAllocator,
    ComputeBudget,
    ScaledRunner,
    backend_policy_from_config,
    compute_tiers_from_config,
)
from siro.schemas import ApprovalScope, GovernedAction

TINY_MLP = "tasks/research/training/tiny_mlp"
GOOD_CONFIG = "CONFIG = {'learning_rate': 0.2, 'epochs': 40, 'hidden_size': 8, 'batch_size': 16, 'seed': 0}\n"


def _make_task(tmp_path, eval_src, *, name="synthetic"):
    """Write a minimal research task whose eval.py is ``eval_src`` and load it."""
    d = tmp_path / "tasks" / name
    (d / "baseline").mkdir(parents=True)
    (d / "task.json").write_text(
        json.dumps(
            {"family": "synthetic", "edit_surface": "noop.py", "primary_metric": "m", "higher_is_better": True}
        ),
        encoding="utf-8",
    )
    (d / "brief.md").write_text("# synthetic\n", encoding="utf-8")
    (d / "baseline" / "noop.py").write_text("VALUE = 1\n", encoding="utf-8")
    (d / "eval.py").write_text(eval_src, encoding="utf-8")
    return load_research_task(d)


def _gate(tmp_path):
    return GovernanceGate(ApprovalLedger(tmp_path / "approvals.jsonl"))


def _allocator(tmp_path, *, tiers=None):
    return ComputeAllocator(
        _gate(tmp_path), tiers=tiers, checkpoints=CheckpointStore(tmp_path / "ckpt")
    )


# --- governed allocation ----------------------------------------------------


def test_default_tier_needs_no_approval(tmp_path):
    alloc = _allocator(tmp_path)
    budget = alloc.allocate("exp", 0)
    assert budget.tier == 0


def test_higher_tier_refused_without_smaller_pass(tmp_path):
    alloc = _allocator(tmp_path)
    # No recorded pass at tier 0 -> cannot jump to tier 1 (promotion-before-budget).
    with pytest.raises(ComputeAllocationError, match="passing tier 0"):
        alloc.allocate("exp", 1)


def test_higher_tier_refused_without_governance(tmp_path):
    alloc = _allocator(tmp_path)
    alloc.record_pass("exp", 0)  # earned the right to *request* tier 1
    with pytest.raises(GovernanceDenied) as exc:
        alloc.allocate("exp", 1)
    # The denial records a pending governance request bound to (experiment, tier).
    assert exc.value.request.action is GovernedAction.BUDGET_INCREASE
    assert "exp" in exc.value.request.target


def test_higher_tier_allocated_with_pass_and_approval(tmp_path):
    gate = _gate(tmp_path)
    alloc = ComputeAllocator(gate, checkpoints=CheckpointStore(tmp_path / "ckpt"))
    alloc.record_pass("exp", 0)
    # Human pre-approves the exact (experiment, tier) change, standing scope.
    req = gate.request(
        GovernedAction.BUDGET_INCREASE,
        target="compute_tier:exp",
        payload={"compute_tier": 1},
        scope=ApprovalScope.STANDING,
    )
    gate.approve(req.request_id, by="alice", scope=ApprovalScope.STANDING)
    budget = alloc.allocate("exp", 1)
    assert budget.tier == 1 and budget.wall_clock_seconds > 0


# --- scaled execution on a real task ---------------------------------------


def test_scaled_run_default_tier_passes_and_checkpoints(tmp_path):
    task = load_research_task(TINY_MLP)
    ckpt = CheckpointStore(tmp_path / "ckpt")
    runner = ScaledRunner(
        _gate(tmp_path),
        archive=ResearchArchive(tmp_path / "research.jsonl"),
        checkpoints=ckpt,
    )
    result = runner.run(task, GOOD_CONFIG, compute_tier=0, experiment_id="mlp")
    assert result.metric.passed
    assert ResearchArchive(tmp_path / "research.jsonl").read_all()  # attempt archived
    state = ckpt.load("mlp")
    assert state["highest_passed_tier"] == 0  # lineage recorded for the next tier


# --- hard ceilings: breach halts and escalates ------------------------------


SLEEPER_EVAL = (
    "import time, json\n"
    "time.sleep(5)\n"
    "print(json.dumps({'primary': 1.0, 'passed': True}))\n"
)
HOG_EVAL = (
    "import time, json\n"
    "x = bytearray(300 * 1024 * 1024)\n"  # ~300MB resident
    "time.sleep(0.6)\n"
    "print(json.dumps({'primary': 1.0, 'passed': True, '_': len(x)}))\n"
)


def test_wall_clock_breach_halts_and_escalates(tmp_path):
    task = _make_task(tmp_path, SLEEPER_EVAL)
    runner = ScaledRunner(
        _gate(tmp_path),
        tiers={0: ComputeBudget(0, 0.5, 512)},  # 0.5s ceiling vs a 5s sleeper
        archive=ResearchArchive(tmp_path / "research.jsonl"),
        checkpoints=CheckpointStore(tmp_path / "ckpt"),
    )
    with pytest.raises(BudgetExceeded) as exc:
        runner.run(task, "", compute_tier=0, experiment_id="slow")
    assert exc.value.kind == "wall_clock"
    # The breach is recorded as a (negative) attempt — the archive stays consistent.
    attempts = ResearchArchive(tmp_path / "research.jsonl").read_all()
    assert attempts and "wall_clock" in attempts[-1].reason


def test_memory_breach_halts_and_escalates(tmp_path):
    task = _make_task(tmp_path, HOG_EVAL)
    runner = ScaledRunner(
        _gate(tmp_path),
        tiers={0: ComputeBudget(0, 10.0, 64)},  # 64MB ceiling vs a ~300MB hog
        archive=ResearchArchive(tmp_path / "research.jsonl"),
        checkpoints=CheckpointStore(tmp_path / "ckpt"),
    )
    with pytest.raises(BudgetExceeded) as exc:
        runner.run(task, "", compute_tier=0, experiment_id="hog")
    assert exc.value.kind == "memory_mb"
    assert exc.value.observed > 64  # peak RSS exceeded the ceiling


def test_breach_preserves_prior_checkpoint(tmp_path):
    # A good run checkpoints; a later breach must not corrupt or delete that checkpoint.
    ckpt = CheckpointStore(tmp_path / "ckpt")
    good = ScaledRunner(
        _gate(tmp_path), archive=ResearchArchive(tmp_path / "r.jsonl"), checkpoints=ckpt
    )
    good.run(load_research_task(TINY_MLP), GOOD_CONFIG, compute_tier=0, experiment_id="exp")
    before = ckpt.load("exp")
    assert before["highest_passed_tier"] == 0

    breacher = ScaledRunner(
        _gate(tmp_path),
        tiers={0: ComputeBudget(0, 0.5, 512)},
        archive=ResearchArchive(tmp_path / "r.jsonl"),
        checkpoints=ckpt,
    )
    with pytest.raises(BudgetExceeded):
        breacher.run(_make_task(tmp_path, SLEEPER_EVAL), "", compute_tier=0, experiment_id="exp")
    # Resume state is intact: the earlier pass is still recorded.
    assert ckpt.load("exp")["highest_passed_tier"] == 0


# --- plane isolation holds at scale -----------------------------------------

NET_PROBE_EVAL = (
    "import socket, json\n"
    "try:\n"
    "    socket.socket().connect(('10.255.255.1', 80))\n"
    "    blocked = False\n"
    "except OSError:\n"
    "    blocked = True\n"
    "print(json.dumps({'primary': 1.0, 'passed': blocked, 'notes': 'net blocked'}))\n"
)


def test_execution_plane_has_no_network_under_run_guarded(tmp_path):
    task = _make_task(tmp_path, NET_PROBE_EVAL)
    runner = ScaledRunner(
        _gate(tmp_path),
        archive=ResearchArchive(tmp_path / "r.jsonl"),
        checkpoints=CheckpointStore(tmp_path / "ckpt"),
    )
    result = runner.run(task, "", compute_tier=0, experiment_id="net")
    # The candidate could not open a socket — network is blocked even at scale.
    assert result.metric.passed


# --- Goal 15: backend policy + process-count ceiling ------------------------


def test_backend_policy_and_tiers_parse_from_tier2_config():
    config = load_config("config/tier2.governed.yaml")
    policy = backend_policy_from_config(config)
    assert policy.default_backend == "local"
    assert policy.hard_backend_above_tier == 0
    assert policy.allow_local_dev is False
    assert policy.requires_hard(0) is False and policy.requires_hard(1) is True
    tiers = compute_tiers_from_config(config)
    assert tiers[0].max_processes == 16  # process-count ceiling carried through


def test_default_tier_runs_on_portable_backend_even_when_hard_required(tmp_path):
    # Tier 0 never requires a hard backend, so the portable default runs and records its identity.
    task = load_research_task(TINY_MLP)
    runner = ScaledRunner(
        _gate(tmp_path),
        policy=BackendPolicy(hard_backend_above_tier=0),
        archive=ResearchArchive(tmp_path / "r.jsonl"),
        checkpoints=CheckpointStore(tmp_path / "ckpt"),
    )
    result = runner.run(task, GOOD_CONFIG, compute_tier=0, experiment_id="mlp")
    assert result.metric.passed
    assert result.backend == "local"


def test_higher_tier_refuses_portable_backend(tmp_path):
    # The backend policy is checked before allocation: a tier needing hard isolation must not
    # silently run on the portable developer monitor.
    task = load_research_task(TINY_MLP)
    runner = ScaledRunner(
        _gate(tmp_path),
        policy=BackendPolicy(hard_backend_above_tier=0, allow_local_dev=False),
        archive=ResearchArchive(tmp_path / "r.jsonl"),
        checkpoints=CheckpointStore(tmp_path / "ckpt"),
    )
    with pytest.raises(BackendPolicyError, match="hard"):
        runner.run(task, GOOD_CONFIG, compute_tier=1, experiment_id="mlp")


def test_local_dev_override_bypasses_backend_policy(tmp_path):
    # With the local-dev override, the portable backend is allowed above the threshold, so the
    # next gate (promotion-before-budget) is what stops an unearned tier — not the backend policy.
    task = load_research_task(TINY_MLP)
    runner = ScaledRunner(
        _gate(tmp_path),
        policy=BackendPolicy(hard_backend_above_tier=0, allow_local_dev=True),
        archive=ResearchArchive(tmp_path / "r.jsonl"),
        checkpoints=CheckpointStore(tmp_path / "ckpt"),
    )
    with pytest.raises(ComputeAllocationError):
        runner.run(task, GOOD_CONFIG, compute_tier=1, experiment_id="mlp")


FORKER_EVAL = (
    "import os, time, json\n"
    "for _ in range(8):\n"
    "    if os.fork() == 0:\n"
    "        time.sleep(2)\n"
    "        os._exit(0)\n"
    "time.sleep(2)\n"
    "print(json.dumps({'primary': 1.0, 'passed': True}))\n"
)


@pytest.mark.skipif(not hasattr(__import__("os"), "fork"), reason="requires os.fork")
def test_process_count_breach_halts_and_escalates(tmp_path):
    task = _make_task(tmp_path, FORKER_EVAL)
    runner = ScaledRunner(
        _gate(tmp_path),
        tiers={0: ComputeBudget(0, 10.0, 512, max_processes=3)},  # 3-process ceiling vs 8 forks
        archive=ResearchArchive(tmp_path / "research.jsonl"),
        checkpoints=CheckpointStore(tmp_path / "ckpt"),
    )
    with pytest.raises(BudgetExceeded) as exc:
        runner.run(task, "", compute_tier=0, experiment_id="fork")
    assert exc.value.kind == "process_count"
    attempts = ResearchArchive(tmp_path / "research.jsonl").read_all()
    assert attempts and "process_count" in attempts[-1].reason
