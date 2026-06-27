"""Goal 27 — drug/life-science pack: two-stage in-silico screening + governed confirmation.

The pack rides on the pack interface (Goal 22), the statistical gate (Goal 24), and the
governed external-experiment boundary (Goal 26). These tests pin the load-bearing bounds:

- the pack loads as a two-regime pack (statistical screening, external-oracle confirmation);
- the offline surrogate screen promotes a real improvement and rejects gamed/un-drug-like ones;
- the screen, fixtures, and held-out surrogate are read-only to agents (edit-surface bound);
- a costly confirmation may only be *proposed* for a candidate that cleared the screen;
- a candidate promotes to *confirmed* only on an ingested, signed assay result bound to a live
  approval — an in-silico score alone never confirms;
- the confirmation adapter never touches the execution plane;
- negative/null screening and assay results are first-class.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from siro.agents.roles import MODEL_ROLES, build_agent
from siro.archive import ModelCallLedger
from siro.config import load_config
from siro.external import (
    ExternalOracleAdapter,
    ExternalResultLedger,
    ingest_external_result,
)
from siro.governance import ApprovalLedger, GovernanceGate
from siro.life_science import (
    ConfirmationNotEarned,
    propose_confirmation,
    screen_clears,
)
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
from siro.schemas import ExternalResultStatus, GateDecision

SCREEN = "packs/life_science/tasks/screening/kinase_binding"
CONFIRM = "packs/life_science/tasks/confirmation/kinase_assay"
SIGNING_KEY = "dev-signing-key"

# A drug-like, synthesizable improvement over the baseline (`scaffold aromatic_ring hbond_donor`).
BETTER = "scaffold aromatic_ring hbond_donor halogen hbond_acceptor\n"
# Inflates predicted affinity with lipophilic/bulky groups but blows past the ADMET logP window.
GAMED = "scaffold aromatic_ring aromatic_ring bulky_group bulky_group halogen halogen\n"

# A small replicate set keeps the statistical org cycle fast in tests.
SMALL_POLICY = StatisticalPolicy(seeds=(7, 19, 31, 53, 71), confidence=0.95)


class _ExplodingSandbox:
    """A sandbox that fails loudly if the confirmation adapter ever runs anything."""

    def __getattr__(self, name):  # pragma: no cover - only hit on a boundary violation
        raise AssertionError(f"confirmation adapter must not use the execution plane ({name!r})")


# --------------------------------------------------------------------------- #
# pack shape: two regimes in one reviewable unit.
# --------------------------------------------------------------------------- #


def test_pack_loads_as_two_stage_pack():
    pack = load_pack("life_science")
    assert pack.id == "life_science"
    # The pack's declared (default) regime is the offline screen.
    assert pack.regime is EvaluatorRegime.STATISTICAL
    assert pack.prompts_dir == Path("packs/life_science/prompts")
    assert pack.references_dir == Path("packs/life_science/references")
    assert {(t.family, t.task_id) for t in discover_research_tasks(None, pack_id="life_science")} == {
        ("screening", "kinase_binding"),
        ("confirmation", "kinase_assay"),
    }


def test_screening_task_is_statistical_confirmation_is_external_oracle():
    screen = load_research_task(SCREEN)
    confirm = load_research_task(CONFIRM)
    # Same pack, different per-task regimes (task.json override).
    assert screen.pack_id == confirm.pack_id == "life_science"
    assert screen.evaluator_regime is EvaluatorRegime.STATISTICAL
    assert confirm.evaluator_regime is EvaluatorRegime.EXTERNAL_ORACLE
    assert confirm.external["action_class"] == "assay"
    assert confirm.external["irreversible"] is True


def test_pack_selected_by_config_only():
    tier0 = load_config("config/tier0.life_science.yaml")
    tier1 = load_config("config/tier1.life_science.yaml")
    assert tier0.pack == "life_science" and tier0.tier == 0
    assert tier1.pack == "life_science" and tier1.tier == 1


# --------------------------------------------------------------------------- #
# screening: read-only scorer + offline surrogate, no real-world action.
# --------------------------------------------------------------------------- #


def test_edit_surface_is_molecule_only_and_surrogate_is_controller_owned():
    task = load_research_task(SCREEN)
    # The only editable surface is molecule.txt; the surrogate lives in hidden/, never in the
    # agent-visible support files, so a candidate cannot edit it (that would need approval).
    assert task.edit_surface == "molecule.txt"
    assert task.allowed_surface.endswith("kinase_binding/baseline/molecule.txt")
    assert "surrogate.json" not in task.support_files
    assert task.hidden_dir is not None and (task.hidden_dir / "surrogate.json").exists()


def test_candidate_referencing_hidden_surrogate_is_rejected():
    task = load_research_task(SCREEN)
    sandbox = Sandbox()
    for peeking in ("scaffold surrogate aromatic_ring\n", "scaffold ../hidden hbond_donor\n"):
        metric = run_research_eval(task, peeking, sandbox)
        assert not metric.passed
        assert "forbidden" in metric.error


def test_unknown_fragment_token_is_rejected():
    task = load_research_task(SCREEN)
    metric = run_research_eval(task, "scaffold magic_group\n", Sandbox())
    assert not metric.passed
    assert "unknown fragment" in metric.error


def test_drug_likeness_and_synthesizability_gate_affinity():
    task = load_research_task(SCREEN)
    sandbox = Sandbox()
    # The gamed candidate has higher predicted affinity than the baseline but is too lipophilic.
    gamed = run_research_eval(task, GAMED, sandbox)
    assert not gamed.passed
    assert "not drug-like" in gamed.error
    # And even if treated as a candidate, the improvement gate refuses a non-passing metric.
    baseline = run_research_eval(task, task.surface_code, sandbox)
    improved, _ = research_improves(gamed, baseline, regime=task.evaluator_regime)
    assert improved is False


def test_screen_promotes_a_real_improvement_under_the_statistical_gate():
    task = load_research_task(SCREEN)
    sandbox = Sandbox()
    baseline = run_research_eval(task, task.surface_code, sandbox)
    candidate = run_research_eval(task, BETTER, sandbox)
    assert baseline.passed and candidate.passed
    assert candidate.primary > baseline.primary  # higher predicted affinity
    # Deterministic surrogate => the statistical interval is a point that still clears the bound.
    assessment = assess_statistical(task, BETTER, task.surface_code, sandbox, policy=SMALL_POLICY)
    assert assessment.evidence.promoted
    assert assessment.evidence.primary_delta_low > 0.0
    gate = research_reproducibility_gate(task, BETTER, sandbox, evidence=assessment.evidence)
    assert gate.decision is GateDecision.PASSED


def test_within_screen_negative_is_recorded_with_reason():
    # A null/failed screen result carries its reason and never passes — first-class negative.
    task = load_research_task(SCREEN)
    metric = run_research_eval(task, GAMED, Sandbox())
    assert not metric.passed
    assert metric.error  # the reason is retained for the archive/memory derivation


# --------------------------------------------------------------------------- #
# screening gates confirmation (Goal 11 promotion-before-budget).
# --------------------------------------------------------------------------- #


def _gate(tmp_path) -> GovernanceGate:
    return GovernanceGate(ApprovalLedger(tmp_path / "approvals.jsonl"))


def _results(tmp_path) -> ExternalResultLedger:
    return ExternalResultLedger(tmp_path / "external_results.jsonl")


def _adapter(tmp_path) -> ExternalOracleAdapter:
    return ExternalOracleAdapter(
        approvals_path=tmp_path / "approvals.jsonl",
        results_path=tmp_path / "external_results.jsonl",
    )


def _screen(candidate: str) -> "object":
    task = load_research_task(SCREEN)
    return assess_statistical(task, candidate, task.surface_code, Sandbox(), policy=SMALL_POLICY)


def test_unscreened_candidate_cannot_be_proposed_for_confirmation(tmp_path):
    gate = _gate(tmp_path)
    confirm = load_research_task(CONFIRM)
    with pytest.raises(ConfirmationNotEarned):
        propose_confirmation(gate, confirm, BETTER.strip(), screen_evidence=None, actor="agent:hyp")
    # And a within-noise / non-promoting screen does not clear either.
    assert not screen_clears(None)


def test_screened_candidate_proposal_carries_the_screen_evidence(tmp_path):
    gate = _gate(tmp_path)
    confirm = load_research_task(CONFIRM)
    assessment = _screen(BETTER)
    assert assessment.evidence.promoted
    req = propose_confirmation(
        gate, confirm, BETTER.strip(), screen_evidence=assessment.evidence, actor="agent:hyp"
    )
    assert gate.status_of(req.request_id) == "pending"  # default-deny; awaits a human
    assert any("in-silico screen" in line for line in req.evidence)


def test_confirmation_requires_signed_approved_result_not_an_insilico_score(tmp_path):
    gate = _gate(tmp_path)
    results = _results(tmp_path)
    confirm = load_research_task(CONFIRM)
    candidate = BETTER.strip()
    assessment = _screen(BETTER)

    # An in-silico screen alone yields no confirmation.
    before = _adapter(tmp_path).evaluate(confirm, candidate, _ExplodingSandbox())
    assert not before.passed and not before.reproducible
    assert "awaiting" in before.error

    # propose (screened) -> approve -> ingest signed result -> confirmed.
    req = propose_confirmation(
        gate, confirm, candidate, screen_evidence=assessment.evidence, actor="agent:hyp"
    )
    gate.approve(req.request_id, by="dr-ruth")
    ingest_external_result(
        gate,
        results,
        req.request_id,
        primary=7.4,
        passed=True,
        operator_id="dr-ruth",
        provenance="lab-notebook-7",
        signing_key=SIGNING_KEY,
    )
    confirmed = _adapter(tmp_path).evaluate(confirm, candidate, _ExplodingSandbox())
    assert confirmed.passed and confirmed.reproducible
    assert confirmed.primary == pytest.approx(7.4)


def test_confirmation_adapter_never_uses_execution_plane(tmp_path):
    gate = _gate(tmp_path)
    results = _results(tmp_path)
    confirm = load_research_task(CONFIRM)
    candidate = BETTER.strip()
    assessment = _screen(BETTER)
    req = propose_confirmation(
        gate, confirm, candidate, screen_evidence=assessment.evidence, actor="agent:hyp"
    )
    gate.approve(req.request_id, by="dr-ruth")
    ingest_external_result(
        gate,
        results,
        req.request_id,
        primary=7.0,
        passed=True,
        operator_id="dr-ruth",
        signing_key=SIGNING_KEY,
    )
    # _ExplodingSandbox raises on any attribute access; a clean evaluate proves no candidate code
    # ran and no instrument/network was reached through the sandbox.
    metric = _adapter(tmp_path).evaluate(confirm, candidate, _ExplodingSandbox())
    assert metric.passed


def test_null_assay_result_is_archived_and_never_confirms(tmp_path):
    gate = _gate(tmp_path)
    results = _results(tmp_path)
    confirm = load_research_task(CONFIRM)
    candidate = BETTER.strip()
    assessment = _screen(BETTER)
    req = propose_confirmation(
        gate, confirm, candidate, screen_evidence=assessment.evidence, actor="agent:hyp"
    )
    gate.approve(req.request_id, by="dr-ruth")
    record = ingest_external_result(
        gate,
        results,
        req.request_id,
        status=ExternalResultStatus.NULL,
        passed=False,
        operator_id="dr-ruth",
        reason="assay inconclusive — compound precipitated",
        signing_key=SIGNING_KEY,
    )
    assert record.status is ExternalResultStatus.NULL
    metric = _adapter(tmp_path).evaluate(confirm, candidate, _ExplodingSandbox())
    assert not metric.passed
    # The negative result stays on the ledger — it is not discarded.
    assert any(r.status is ExternalResultStatus.NULL for r in results.records())


# --------------------------------------------------------------------------- #
# full org lifecycle on the in-silico screen (inner loop).
# --------------------------------------------------------------------------- #


def _responses(candidate_code: str) -> dict[str, str]:
    payloads = {
        "hypothesis": {
            "statement": "add an H-bond acceptor and a halogen to raise affinity while staying drug-like",
            "proposed_experiment": "extend the fragment set with halogen + hbond_acceptor",
            "required_metrics": ["predicted_affinity"],
            "expected_failure_mode": "too lipophilic, fails ADMET window",
        },
        "literature": {
            "prior_art": "halogen bonding and H-bond acceptors improve kinase affinity",
            "related_work": ["fragment-based design"],
            "novelty": "incremental",
            "is_duplicate": False,
            "refinements": "keep logP within window",
            "caveats": "do not stack lipophilic groups",
        },
        "implementation": {
            "code": candidate_code,
            "implementation_notes": "balanced fragment set",
            "expected_impact": "higher predicted affinity, still drug-like",
            "known_risks": "",
        },
        "evaluation": {
            "pass_fail": True,
            "metric_deltas": "predicted_affinity 5.0 -> 6.9",
            "regression_report": "drug-like and synthesizable",
            "suggested_follow_up": "propose a confirmation assay",
        },
        "safety": {
            "classification": "safe",
            "risk_notes": "in-silico screen only; wet-lab is human-gated",
            "required_mitigations": [],
            "escalate": False,
        },
        "interpretation": {
            "result_summary": "higher predicted affinity, still drug-like",
            "likely_explanation": "added H-bonding and a halogen",
            "confidence": 0.9,
            "follow_up_experiments": [],
            "memory_entry_draft": "balanced fragments improve the screen",
        },
        "memory": {
            "strategy": "balance affinity against ADMET",
            "lessons_learned": ["don't stack lipophilic groups"],
            "retrieval_tags": ["screening", "kinase"],
            "follow_up": "",
        },
        "meta_research": {
            "target": "life-science pack prompts",
            "proposed_change": "remind to check logP before adding lipophilic fragments",
            "expected_benefit": "fewer ADMET failures",
            "validation_experiment": "A/B on the fixed screening task",
            "rollback_plan": "restore prompt",
        },
    }
    return {role: json.dumps(payloads[role]) for role in MODEL_ROLES}


def test_screen_full_lifecycle_records_attempt_and_memory(tmp_path):
    pack = load_pack("life_science")
    agents = {
        role: build_agent(role, ScriptedModelClient([text], provider=f"p-{role}"))
        for role, text in _responses(BETTER).items()
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

    result = orch.run_research_cycle("improve the kinase screen", SCREEN)

    assert result.promoted
    [attempt] = archive.read_all()
    assert attempt.pack_id == "life_science"
    assert attempt.status.value == "promoted"
    assert attempt.statistical is not None and attempt.statistical.promoted
    [entry] = memory.all_entries()
    assert entry.pack_id == "life_science"
    assert entry.status.value == "promoted"
