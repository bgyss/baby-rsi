"""Goal 23 — formal mathematics pack backed by an offline lake build."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from siro.agents.roles import MODEL_ROLES, build_agent
from siro.archive import ModelCallLedger
from siro.config import load_config
from siro.memory import ResearchMemory
from siro.model_client import ScriptedModelClient
from siro.orchestrator import Orchestrator
from siro.packs import EvaluatorRegime, load_pack
from siro.research import (
    ResearchArchive,
    discover_research_tasks,
    load_research_task,
    research_improves,
    research_reproducibility_gate,
    run_research_eval,
)
from siro.sandbox import Sandbox
from siro.schemas import GateDecision

ADD_ZERO = "packs/math/tasks/lemma/add_zero"
AND_COMM = "packs/math/tasks/proof_improvement/and_comm_shorter"

ADD_ZERO_GOOD = """\
theorem add_zero_candidate (n : Nat) : n + 0 = n := by
  exact Nat.add_zero n
"""

AND_COMM_SHORT = """\
theorem and_comm_candidate (p q : Prop) : p ∧ q -> q ∧ p := by
  intro h
  exact And.intro h.right h.left
"""


def _install_fake_lake(tmp_path: Path, monkeypatch) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    lake = bin_dir / "lake"
    lake.write_text(
        """#!/usr/bin/env python3
from pathlib import Path
import sys

if sys.argv[1:] != ["build"]:
    print("expected lake build", file=sys.stderr)
    sys.exit(2)
proof = Path("Proof.lean").read_text(encoding="utf-8")
check = Path("HiddenCheck.lean").read_text(encoding="utf-8")
if any(token in proof.lower() for token in ("sorry", "axiom", "unsafe", "admit")):
    print("placeholder proof rejected", file=sys.stderr)
    sys.exit(1)
if "add_zero_candidate" in check and "n + 0 = n" not in proof:
    print("wrong add_zero theorem statement", file=sys.stderr)
    sys.exit(1)
if "and_comm_candidate" in check and "p ∧ q -> q ∧ p" not in proof:
    print("wrong and_comm theorem statement", file=sys.stderr)
    sys.exit(1)
if "HiddenCheck" in proof:
    print("hidden check reference rejected", file=sys.stderr)
    sys.exit(1)
sys.exit(0)
""",
        encoding="utf-8",
    )
    lake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    return lake


def test_math_pack_loads_as_exact_regime():
    pack = load_pack("math")
    assert pack.id == "math"
    assert pack.regime is EvaluatorRegime.EXACT
    assert pack.prompts_dir == Path("packs/math/prompts")
    assert pack.references_dir == Path("packs/math/references")
    assert {t.task_id for t in discover_research_tasks(None, pack_id="math")} == {
        "add_zero",
        "and_comm_shorter",
    }


def test_math_evaluator_verifies_and_rejects_proofs(tmp_path, monkeypatch):
    _install_fake_lake(tmp_path, monkeypatch)
    sandbox = Sandbox()
    task = load_research_task(ADD_ZERO)

    baseline = run_research_eval(task, task.surface_code, sandbox)
    assert not baseline.passed
    assert "forbidden" in baseline.error

    good = run_research_eval(task, ADD_ZERO_GOOD, sandbox)
    assert good.passed
    assert good.primary == 1.0
    assert good.secondary["proof_length"] > 0

    weakened = "theorem add_zero_candidate (n : Nat) : True := by\n  trivial\n"
    bad = run_research_eval(task, weakened, sandbox)
    assert not bad.passed
    assert "wrong add_zero theorem statement" in bad.error

    peeking = ADD_ZERO_GOOD + "\n#check HiddenCheck\n"
    hidden = run_research_eval(task, peeking, sandbox)
    assert not hidden.passed
    assert "hidden check" in hidden.error


def test_math_exact_reproducibility_and_secondary_improvement(tmp_path, monkeypatch):
    _install_fake_lake(tmp_path, monkeypatch)
    task = load_research_task(AND_COMM)
    sandbox = Sandbox()
    baseline = run_research_eval(task, task.surface_code, sandbox)
    candidate = run_research_eval(task, AND_COMM_SHORT, sandbox)

    assert baseline.passed and candidate.passed
    assert candidate.primary == baseline.primary == 1.0
    assert candidate.secondary["proof_length"] < baseline.secondary["proof_length"]
    improved, why = research_improves(candidate, baseline)
    assert improved
    assert "proof_length" in why
    assert research_reproducibility_gate(task, AND_COMM_SHORT, sandbox).decision is GateDecision.PASSED


def test_math_pack_runs_with_real_lake_when_available():
    if shutil.which("lake") is None:
        return
    task = load_research_task(ADD_ZERO)
    metric = run_research_eval(task, ADD_ZERO_GOOD, Sandbox())
    assert metric.passed
    assert metric.primary == 1.0
    assert "lake build verified" in metric.notes


def _responses(candidate_code: str) -> dict[str, str]:
    payloads = {
        "hypothesis": {
            "statement": "use the pinned core lemma",
            "proposed_experiment": "replace the placeholder proof with Nat.add_zero",
            "required_metrics": ["proof_verified"],
            "expected_failure_mode": "wrong theorem statement",
        },
        "literature": {
            "prior_art": "Nat.add_zero is in the pinned corpus",
            "related_work": ["Nat.add_zero"],
            "novelty": "incremental",
            "is_duplicate": False,
            "refinements": "use exact",
            "caveats": "",
        },
        "implementation": {
            "code": candidate_code,
            "implementation_notes": "replace sorry with exact proof",
            "expected_impact": "proof verifies",
            "known_risks": "",
        },
        "evaluation": {
            "pass_fail": True,
            "metric_deltas": "proof_verified 0 -> 1",
            "regression_report": "no regression",
            "suggested_follow_up": "",
        },
        "safety": {
            "classification": "safe",
            "risk_notes": "",
            "required_mitigations": [],
            "escalate": False,
        },
        "interpretation": {
            "result_summary": "proof verified",
            "likely_explanation": "core lemma solved the task",
            "confidence": 0.9,
            "follow_up_experiments": [],
            "memory_entry_draft": "Nat.add_zero verified add_zero",
        },
        "memory": {
            "strategy": "use pinned core lemma",
            "lessons_learned": ["Nat.add_zero verified add_zero"],
            "retrieval_tags": ["Nat.add_zero"],
            "follow_up": "",
        },
        "meta_research": {
            "target": "math pack prompts",
            "proposed_change": "retrieve Nat lemmas first",
            "expected_benefit": "faster proof search",
            "validation_experiment": "A/B on fixed math tasks",
            "rollback_plan": "restore prompt",
        },
    }
    return {role: json.dumps(payloads[role]) for role in MODEL_ROLES}


def test_math_pack_full_lifecycle_records_attempt_and_memory(tmp_path, monkeypatch):
    _install_fake_lake(tmp_path, monkeypatch)
    pack = load_pack("math")
    agents = {
        role: build_agent(role, ScriptedModelClient([text], provider=f"p-{role}"))
        for role, text in _responses(ADD_ZERO_GOOD).items()
    }
    archive = ResearchArchive(tmp_path / "attempts.jsonl")
    memory = ResearchMemory(tmp_path / "memory.jsonl")
    orch = Orchestrator(
        agents=agents,
        memory=memory,
        ledger=ModelCallLedger(tmp_path / "model_calls.jsonl"),
        research_archive=archive,
        pack=pack,
    )

    result = orch.run_research_cycle("prove add_zero", ADD_ZERO)

    assert result.promoted
    assert result.metric is not None and result.metric.passed
    [attempt] = archive.read_all()
    assert attempt.pack_id == "math"
    assert attempt.status.value == "promoted"
    [entry] = memory.all_entries()
    assert entry.pack_id == "math"
    assert entry.status.value == "promoted"


def test_math_pack_selected_by_config_only():
    tier0 = load_config("config/tier0.math.yaml")
    tier1 = load_config("config/tier1.math.yaml")
    assert tier0.pack == "math"
    assert tier1.pack == "math"
