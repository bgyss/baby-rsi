"""Goal 24 — statistical reproducibility gate, fully offline.

The statistical regime promotes a *noisy* evaluator only when the candidate's oriented gain
over the incumbent clears a confidence bound across N fixed seeded replicates. These tests
use a synthetic stochastic ``eval.py`` (whose noise depends on the controller-set
``SIRO_EVAL_SEED``) to check the two boundary behaviors — a within-noise win does not promote,
a bound-clearing win does — plus the determinism of the decision and the fact that the seeds,
N, and confidence are harness parameters a candidate cannot set or read.
"""

from __future__ import annotations

import dataclasses
import json
import textwrap

from siro.agents.roles import MODEL_ROLES, build_agent
from siro.archive import ModelCallLedger
from siro.gates import scan
from siro.memory import ResearchMemory
from siro.model_client import ScriptedModelClient
from siro.orchestrator import Orchestrator
from siro.packs import EvaluatorRegime, load_pack
from siro.research import (
    ResearchArchive,
    StatisticalPolicy,
    assess_statistical,
    load_research_task,
    research_improves,
    research_reproducibility_gate,
)
from siro.sandbox import Sandbox
from siro.schemas import AttemptStatus, GateDecision

# A small, fixed replicate set keeps the tests fast while still exercising the t-interval.
POLICY = StatisticalPolicy(seeds=(11, 23, 47, 89, 101, 211, 307), confidence=0.95)

# A synthetic stochastic evaluator: the primary metric is the candidate-declared QUALITY plus
# seed-dependent Gaussian noise. The noise stream is keyed by both the seed and the candidate's
# QUALITY, so the incumbent and a candidate draw *independent* noise at the same seed (the
# paired deltas therefore carry real variance, exactly like a real in-silico evaluator).
EVAL_PY = textwrap.dedent(
    """
    import hashlib
    import json
    import os
    import random

    import solution

    seed = int(os.environ.get("SIRO_EVAL_SEED", "0"))
    quality = float(getattr(solution, "QUALITY", 0.0))
    code_id = int(hashlib.sha256(repr(quality).encode()).hexdigest(), 16) % 100000
    rng = random.Random(seed * 100000 + code_id)
    noise = rng.gauss(0.0, 1.0)
    print(json.dumps({"primary": quality + noise, "passed": True}))
    """
).strip()


def _write_statistical_task(tmp_path):
    """Write a stochastic research task and load it as a ``statistical``-regime task."""
    root = tmp_path / "noisy_sim"
    (root / "baseline").mkdir(parents=True)
    (root / "task.json").write_text(
        json.dumps(
            {
                "family": "simulation",
                "edit_surface": "solution.py",
                "objective": "raise the simulated score",
                "primary_metric": "score",
                "higher_is_better": True,
                "budget_seconds": 10,
            }
        ),
        encoding="utf-8",
    )
    (root / "brief.md").write_text("# Noisy simulator\nImprove `QUALITY`.\n", encoding="utf-8")
    (root / "baseline" / "solution.py").write_text("QUALITY = 0.0\n", encoding="utf-8")
    (root / "eval.py").write_text(EVAL_PY + "\n", encoding="utf-8")
    task = load_research_task(root)
    # The pack is the default (ml) here; force the statistical regime as a real pack would
    # declare it. Nothing about the deterministic packs changes.
    return dataclasses.replace(task, evaluator_regime=EvaluatorRegime.STATISTICAL)


def _write_statistical_pack(tmp_path):
    """Build a minimal domain pack that declares the ``statistical`` regime + one noisy task."""
    root = tmp_path / "packs"
    pack = root / "noisy"
    (pack / "tasks" / "simulation" / "tune").mkdir(parents=True)
    (pack / "pack.toml").write_text(
        'id = "noisy"\n'
        'title = "Noisy simulator pack"\n'
        'version = "0.1.0"\n'
        'evaluator_regime = "statistical"\n',
        encoding="utf-8",
    )
    (pack / "evaluator.py").write_text(
        "from siro.packs import EvalPyAdapter, EvaluatorRegime\n\n\n"
        "def get_adapter(regime: EvaluatorRegime) -> EvalPyAdapter:\n"
        "    return EvalPyAdapter(regime=regime)\n",
        encoding="utf-8",
    )
    task = pack / "tasks" / "simulation" / "tune"
    (task / "baseline").mkdir()
    (task / "task.json").write_text(
        json.dumps(
            {
                "family": "simulation",
                "edit_surface": "solution.py",
                "objective": "raise the simulated score",
                "primary_metric": "score",
                "higher_is_better": True,
                "budget_seconds": 10,
            }
        ),
        encoding="utf-8",
    )
    (task / "brief.md").write_text("# Noisy simulator\nImprove `QUALITY`.\n", encoding="utf-8")
    (task / "baseline" / "solution.py").write_text("QUALITY = 0.0\n", encoding="utf-8")
    (task / "eval.py").write_text(EVAL_PY + "\n", encoding="utf-8")
    return load_pack("noisy", root=root), str(task)


def test_org_cycle_promotes_a_bound_clearing_noisy_candidate_and_records_evidence(tmp_path):
    pack, task_dir = _write_statistical_pack(tmp_path)
    mem = ResearchMemory(tmp_path / "memory.jsonl")
    responses = {
        "hypothesis": {
            "statement": "raise QUALITY",
            "proposed_experiment": "set QUALITY high",
            "required_metrics": ["score"],
            "predicted_result": "higher score",
            "expected_failure": "none",
        },
        "literature": {"novelty": "incremental", "is_duplicate": False, "prior_art": "none"},
        "implementation": {"code": "QUALITY = 10.0\n", "implementation_notes": "raise quality"},
        "evaluation": {"pass_fail": True, "regression_report": "score up"},
        "safety": {"classification": "safe", "escalate": False},
        "interpretation": {
            "result_summary": "works",
            "confidence": 0.9,
            "follow_up_experiments": [],
        },
        "memory": {
            "strategy": "raise-quality",
            "lessons_learned": ["bigger is better"],
            "retrieval_tags": ["sim"],
            "follow_up": "",
        },
        "meta_research": {"proposed_change": "none", "target": "retrieval_limit", "rollback_plan": "revert"},
    }
    agents = {}
    for role in MODEL_ROLES:
        provider = "openai" if role == "safety" else "anthropic"
        agents[role] = build_agent(
            role,
            ScriptedModelClient([json.dumps(responses[role])], provider=provider, model=provider),
            memory=mem,
            task_id="tune",
            allowed_surfaces=[f"{task_dir}/baseline/solution.py"],
        )
    orch = Orchestrator(
        agents,
        memory=mem,
        ledger=ModelCallLedger(tmp_path / "model_calls.jsonl"),
        research_archive=ResearchArchive(tmp_path / "research_attempts.jsonl"),
        require_cross_model=True,
        pack=pack,
        statistical_policy=POLICY,
    )

    result = orch.run_research_cycle("raise the score", task_dir)

    assert result.promotion_decision is GateDecision.PASSED
    attempts = ResearchArchive(tmp_path / "research_attempts.jsonl").read_all()
    assert len(attempts) == 1
    attempt = attempts[0]
    assert attempt.status is AttemptStatus.PROMOTED
    # The statistical evidence is recorded on the attempt: seeds, replicate count, interval.
    assert attempt.statistical is not None
    assert attempt.statistical.seeds == list(POLICY.seeds)
    assert attempt.statistical.replicates == len(POLICY.seeds)
    assert attempt.statistical.promoted is True
    assert attempt.statistical.primary_delta_low > 0.0


def test_within_noise_candidate_does_not_promote(tmp_path):
    task = _write_statistical_task(tmp_path)
    sandbox = Sandbox()
    within_noise = "QUALITY = 0.2\n"  # << the unit noise std — a lucky draw, not a real gain
    assessment = assess_statistical(task, within_noise, task.surface_code, sandbox, policy=POLICY)
    evidence = assessment.evidence

    assert evidence.reproducible
    assert not evidence.promoted
    # The interval must include "no improvement".
    assert evidence.primary_delta_low <= 0.0 <= evidence.primary_delta_high

    improved, _ = research_improves(
        assessment.candidate_metric,
        assessment.baseline_metric,
        regime=EvaluatorRegime.STATISTICAL,
        evidence=evidence,
    )
    assert improved is False
    gate = research_reproducibility_gate(task, within_noise, sandbox, evidence=evidence)
    assert gate.decision is GateDecision.FAILED


def test_bound_clearing_candidate_promotes(tmp_path):
    task = _write_statistical_task(tmp_path)
    sandbox = Sandbox()
    clear_win = "QUALITY = 10.0\n"  # >> the noise std — clears the confidence bound
    assessment = assess_statistical(task, clear_win, task.surface_code, sandbox, policy=POLICY)
    evidence = assessment.evidence

    assert evidence.reproducible
    assert evidence.promoted
    assert evidence.primary_delta_low > 0.0  # the interval excludes zero on the better side

    improved, _ = research_improves(
        assessment.candidate_metric,
        assessment.baseline_metric,
        regime=EvaluatorRegime.STATISTICAL,
        evidence=evidence,
    )
    assert improved is True
    gate = research_reproducibility_gate(task, clear_win, sandbox, evidence=evidence)
    assert gate.decision is GateDecision.PASSED


def test_decision_is_reproducible_on_the_same_seeds(tmp_path):
    task = _write_statistical_task(tmp_path)
    sandbox = Sandbox()
    candidate = "QUALITY = 10.0\n"
    first = assess_statistical(task, candidate, task.surface_code, sandbox, policy=POLICY).evidence
    second = assess_statistical(task, candidate, task.surface_code, sandbox, policy=POLICY).evidence

    # Same seeds -> identical interval and identical decision, even though the metric is noisy.
    assert first.seeds == second.seeds == list(POLICY.seeds)
    assert first.per_seed_primary_delta == second.per_seed_primary_delta
    assert first.primary_delta_low == second.primary_delta_low
    assert first.primary_delta_high == second.primary_delta_high
    assert first.promoted == second.promoted


def test_seeds_and_params_are_recorded_on_the_evidence(tmp_path):
    task = _write_statistical_task(tmp_path)
    sandbox = Sandbox()
    evidence = assess_statistical(
        task, "QUALITY = 10.0\n", task.surface_code, sandbox, policy=POLICY
    ).evidence
    assert evidence.replicates == len(POLICY.seeds)
    assert evidence.confidence == POLICY.confidence
    assert evidence.seeds == list(POLICY.seeds)
    assert len(evidence.per_seed_primary_delta) == len(POLICY.seeds)
    assert evidence.primary_delta_low <= evidence.primary_delta_mean <= evidence.primary_delta_high


def test_seed_is_unreachable_by_a_candidate():
    """The replicate seed is a harness parameter: a candidate that reads it trips the gate."""
    peeking = "import os\nSEED = os.environ['SIRO_EVAL_SEED']\nQUALITY = 99.0\n"
    findings = scan(peeking)
    assert any(category == "env_read" for category, _ in findings)


def test_non_statistical_regimes_take_the_rerun_path(tmp_path):
    """The exact / seeded-deterministic regimes keep the historical rerun-agreement path.

    They supply no replicate seed, so the evaluator is deterministic and honest reruns agree —
    the gate behavior is unchanged by Goal 24 (the statistical regime is the only opt-in).
    """
    task = _write_statistical_task(tmp_path)
    sandbox = Sandbox()
    for regime in (EvaluatorRegime.EXACT, EvaluatorRegime.SEEDED_DETERMINISTIC):
        det_task = dataclasses.replace(task, evaluator_regime=regime)
        gate = research_reproducibility_gate(det_task, "QUALITY = 10.0\n", sandbox)
        assert gate.decision is GateDecision.PASSED


def test_confidence_interval_is_a_strict_generalization_of_exact():
    """A degenerate (zero-variance) sample collapses to a point at the mean.

    So a deterministic positive gain still clears the bound and a deterministic zero gain does
    not — the statistical policy never promotes on noise and never *loosens* the exact gate.
    """
    from siro.research import _confidence_interval

    mean, low, high = _confidence_interval([3.0, 3.0, 3.0, 3.0], 0.95)
    assert mean == low == high == 3.0
    mean0, low0, high0 = _confidence_interval([0.0, 0.0, 0.0], 0.95)
    assert mean0 == low0 == high0 == 0.0
