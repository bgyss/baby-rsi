"""Goal 25 — chip-design pack: offline Yosys equivalence + PPA synthesis.

Toolchain-independent tests cover pack loading, the edit-surface bound, and the candidate
guards. The equivalence/area behavior is checked against **real Yosys** when it is on PATH
(provisioned by nix/mise) and skipped otherwise. The statistical-PPA behavior (within-noise
does not promote, a clear win does) uses a fake Yosys double that injects controlled
measurement noise, so it runs everywhere.
"""

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
    StatisticalPolicy,
    assess_statistical,
    discover_research_tasks,
    load_research_task,
    research_improves,
    research_reproducibility_gate,
    run_research_eval,
)
from siro.sandbox import Sandbox
from siro.schemas import GateDecision

RTL = "packs/chip/tasks/rtl_area/redundant_logic"
RECIPE = "packs/chip/tasks/synth_recipe/recipe_tuning"

FACTORED = "module top(input a, input b, input c, output y);\n  assign y = a & (b | c);\nendmodule\n"
WRONG = "module top(input a, input b, input c, output y);\n  assign y = a & b & c;\nendmodule\n"

HAVE_YOSYS = shutil.which("yosys") is not None
# A small replicate set keeps the statistical org cycle fast in tests.
SMALL_POLICY = StatisticalPolicy(seeds=(7, 19, 31, 53, 71), confidence=0.95)


# --- toolchain-independent --------------------------------------------------


def test_chip_pack_loads_as_statistical_regime():
    pack = load_pack("chip")
    assert pack.id == "chip"
    assert pack.regime is EvaluatorRegime.STATISTICAL
    assert pack.prompts_dir == Path("packs/chip/prompts")
    assert pack.references_dir == Path("packs/chip/references")
    assert {(t.family, t.task_id) for t in discover_research_tasks(None, pack_id="chip")} == {
        ("rtl_area", "redundant_logic"),
        ("synth_recipe", "recipe_tuning"),
    }


def test_edit_surface_is_design_only_and_reference_is_controller_owned():
    task = load_research_task(RTL)
    # The only editable surface is design.v; the reference lives in hidden/, never in the
    # agent-visible support files, so a candidate cannot edit it (that would need approval).
    assert task.edit_surface == "design.v"
    assert task.allowed_surface.endswith("redundant_logic/baseline/design.v")
    assert "golden.v" not in task.support_files
    assert "reference.json" not in task.support_files
    assert task.hidden_dir is not None and (task.hidden_dir / "reference.json").exists()


def test_recipe_task_keeps_fixed_design_read_only():
    task = load_research_task(RECIPE)
    assert task.edit_surface == "recipe.txt"
    # The fixed design is a read-only support file, not the edit surface.
    assert "circuit.v" in task.support_files
    assert task.allowed_surface.endswith("recipe_tuning/baseline/recipe.txt")


def test_candidate_referencing_hidden_reference_is_rejected_before_synthesis():
    task = load_research_task(RTL)
    sandbox = Sandbox()
    peeking = "module top(input a, input b, input c, output y);\n  // read golden.v\n  assign y = a & (b | c);\nendmodule\n"
    metric = run_research_eval(task, peeking, sandbox)
    assert not metric.passed
    assert "forbidden" in metric.error


def test_recipe_allowlist_rejects_non_optimization_commands():
    task = load_research_task(RECIPE)
    sandbox = Sandbox()
    for evil in ("read_verilog golden.v\nopt\n", "opt; tee -o /tmp/x stat\n", "write_verilog out.v\n"):
        metric = run_research_eval(task, evil, sandbox)
        assert not metric.passed
        assert "forbidden" in metric.error or "not in the allowed" in metric.error


def test_chip_pack_selected_by_config_only():
    tier0 = load_config("config/tier0.chip.yaml")
    tier1 = load_config("config/tier1.chip.yaml")
    assert tier0.pack == "chip" and tier0.tier == 0
    assert tier1.pack == "chip" and tier1.tier == 1


# --- real Yosys: equivalence gates PPA --------------------------------------


def test_non_equivalent_design_never_promotes_regardless_of_area():
    if not HAVE_YOSYS:
        return
    task = load_research_task(RTL)
    sandbox = Sandbox()
    # `a & b & c` is smaller than the reference but computes a different function.
    metric = run_research_eval(task, WRONG, sandbox)
    assert not metric.passed
    assert "not formally equivalent" in metric.error
    # Even if we (wrongly) treated it as an improvement, the gate refuses it.
    baseline = run_research_eval(task, task.surface_code, sandbox)
    improved, _ = research_improves(metric, baseline, regime=task.evaluator_regime)
    assert improved is False


def test_area_reduction_is_reproducible_and_improves():
    if not HAVE_YOSYS:
        return
    task = load_research_task(RTL)
    sandbox = Sandbox()
    baseline = run_research_eval(task, task.surface_code, sandbox)
    candidate = run_research_eval(task, FACTORED, sandbox)
    assert baseline.passed and candidate.passed
    assert candidate.primary < baseline.primary  # fewer cells (lower is better)
    # Deterministic area => the statistical interval is a point that still clears the bound.
    assessment = assess_statistical(task, FACTORED, task.surface_code, sandbox, policy=SMALL_POLICY)
    assert assessment.evidence.promoted
    assert assessment.evidence.primary_delta_low > 0.0
    gate = research_reproducibility_gate(task, FACTORED, sandbox, evidence=assessment.evidence)
    assert gate.decision is GateDecision.PASSED


def test_recipe_tuning_reduces_area():
    if not HAVE_YOSYS:
        return
    task = load_research_task(RECIPE)
    sandbox = Sandbox()
    baseline = run_research_eval(task, task.surface_code, sandbox)
    candidate = run_research_eval(task, "opt -full\nabc -g AND,OR\n", sandbox)
    assert baseline.passed and candidate.passed
    assert candidate.primary < baseline.primary


# --- fake Yosys: the statistical PPA gate rejects within-noise wins ----------

# A noisy synthesis double: equivalence always holds; the reported cell count is a
# design-declared nominal area (`// AREA=N`) plus seed-dependent measurement noise keyed by the
# seed and the design's identity (so candidate and incumbent draw independent noise per seed).
FAKE_YOSYS = """#!/usr/bin/env python3
import hashlib, os, random, re, sys
from pathlib import Path

script = sys.argv[2] if len(sys.argv) > 2 else ""
if "miter" in script or "sat " in script:
    sys.exit(0)  # always equivalent
design = Path("design.v").read_text()
m = re.search(r"AREA=(\\d+)", design)
nominal = int(m.group(1)) if m else 8
seed = int(os.environ.get("SIRO_EVAL_SEED", "0"))
code_id = int(hashlib.sha256(design.encode()).hexdigest(), 16) % 100000
rng = random.Random(seed * 100000 + code_id)
cells = max(0, int(round(nominal + rng.gauss(0.0, 2.0))))
print("   %d cells" % cells)
"""


def _install_fake_yosys(tmp_path: Path, monkeypatch) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "yosys"
    fake.write_text(FAKE_YOSYS, encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")


def _design(area: int, tag: str) -> str:
    # Distinct, equivalent designs with a declared nominal area; `tag` varies the source so the
    # noise stream differs between candidate and incumbent at the same seed.
    return (
        f"module top(input a, input b, input c, output y); // AREA={area} {tag}\n"
        "  assign y = a & (b | c);\n"
        "endmodule\n"
    )


def test_within_noise_ppa_fluctuation_does_not_promote(tmp_path, monkeypatch):
    _install_fake_yosys(tmp_path, monkeypatch)
    task = load_research_task(RTL)
    sandbox = Sandbox()
    baseline = _design(10, "base")
    within_noise = _design(10, "cand")  # same nominal area; any "win" is pure noise
    assessment = assess_statistical(task, within_noise, baseline, sandbox, policy=SMALL_POLICY)
    assert assessment.evidence.reproducible
    assert not assessment.evidence.promoted
    assert assessment.evidence.primary_delta_low <= 0.0 <= assessment.evidence.primary_delta_high


def test_clear_ppa_improvement_promotes(tmp_path, monkeypatch):
    _install_fake_yosys(tmp_path, monkeypatch)
    task = load_research_task(RTL)
    sandbox = Sandbox()
    baseline = _design(12, "base")
    clear_win = _design(4, "cand")  # nominal 8 cells smaller than the incumbent
    assessment = assess_statistical(task, clear_win, baseline, sandbox, policy=SMALL_POLICY)
    assert assessment.evidence.promoted
    assert assessment.evidence.primary_delta_low > 0.0


# --- full org lifecycle (real Yosys) ----------------------------------------


def _responses(candidate_code: str) -> dict[str, str]:
    payloads = {
        "hypothesis": {
            "statement": "factor the shared AND",
            "proposed_experiment": "rewrite y as a & (b | c)",
            "required_metrics": ["area_cells"],
            "expected_failure_mode": "non-equivalent rewrite",
        },
        "literature": {
            "prior_art": "boolean factoring reduces gate count",
            "related_work": ["distributive law"],
            "novelty": "incremental",
            "is_duplicate": False,
            "refinements": "share the common term",
            "caveats": "must stay equivalent",
        },
        "implementation": {
            "code": candidate_code,
            "implementation_notes": "factor a out",
            "expected_impact": "fewer cells",
            "known_risks": "",
        },
        "evaluation": {
            "pass_fail": True,
            "metric_deltas": "area_cells 3 -> 2",
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
            "result_summary": "smaller equivalent design",
            "likely_explanation": "factoring removed a duplicate AND",
            "confidence": 0.9,
            "follow_up_experiments": [],
            "memory_entry_draft": "factoring reduced area",
        },
        "memory": {
            "strategy": "factor shared terms",
            "lessons_learned": ["factoring cuts cells"],
            "retrieval_tags": ["area"],
            "follow_up": "",
        },
        "meta_research": {
            "target": "chip pack prompts",
            "proposed_change": "suggest factoring first",
            "expected_benefit": "faster area wins",
            "validation_experiment": "A/B on fixed chip tasks",
            "rollback_plan": "restore prompt",
        },
    }
    return {role: json.dumps(payloads[role]) for role in MODEL_ROLES}


def test_chip_pack_full_lifecycle_records_attempt_and_memory(tmp_path):
    if not HAVE_YOSYS:
        return
    pack = load_pack("chip")
    agents = {
        role: build_agent(role, ScriptedModelClient([text], provider=f"p-{role}"))
        for role, text in _responses(FACTORED).items()
    }
    archive = ResearchArchive(tmp_path / "attempts.jsonl")
    memory = ResearchMemory(tmp_path / "memory.jsonl")
    orch = Orchestrator(
        agents=agents,
        memory=memory,
        ledger=ModelCallLedger(tmp_path / "model_calls.jsonl"),
        research_archive=archive,
        pack=pack,
        statistical_policy=SMALL_POLICY,
    )

    result = orch.run_research_cycle("reduce area", RTL)

    assert result.promoted
    [attempt] = archive.read_all()
    assert attempt.pack_id == "chip"
    assert attempt.status.value == "promoted"
    assert attempt.statistical is not None and attempt.statistical.promoted
    [entry] = memory.all_entries()
    assert entry.pack_id == "chip"
    assert entry.status.value == "promoted"
