"""Tests for the governed external-experiment boundary (Goal 26).

The org may *propose* a real-world experiment but may only *apply* its result through a human
approval and an objective, signed metric. These tests pin the bounds: agents cannot approve or
attest; a result promotes only when bound to a live, matching approval; an unapproved /
expired / revoked / hash-mismatched / unsigned result is rejected and logged; the execution
plane runs no part of the action; and negative/null results are first-class.
"""

from __future__ import annotations

import pytest

from siro.external import (
    ExternalOracleAdapter,
    ExternalResultLedger,
    ExternalResultRejected,
    external_spec_for,
    ingest_external_result,
    propose_external_experiment,
    resolve_external_result,
    spec_content_hash,
)
from siro.governance import ApprovalLedger, GovernanceGate
from siro.packs import EvaluatorRegime
from siro.research import ResearchTask, research_improves
from siro.schemas import ExternalResultStatus, GovernedAction

SIGNING_KEY = "dev-signing-key"


def _task(candidate_id: str = "assay_task", *, primary_name: str = "potency") -> ResearchTask:
    return ResearchTask(
        task_id=candidate_id,
        family="assay",
        path=f"packs/life/tasks/{candidate_id}",
        objective="maximize measured potency",
        brief="brief",
        edit_surface="candidate.txt",
        surface_code="compound-A",
        support_files={},
        eval_path=None,  # type: ignore[arg-type]
        hidden_dir=None,
        primary_name=primary_name,
        higher_is_better=True,
        budget_seconds=1.0,
        evaluator_regime=EvaluatorRegime.EXTERNAL_ORACLE,
        external={"action_class": "assay", "cost_usd": 5000.0, "risk": "high"},
    )


def _gate(tmp_path) -> GovernanceGate:
    return GovernanceGate(ApprovalLedger(tmp_path / "approvals.jsonl"))


def _results(tmp_path) -> ExternalResultLedger:
    return ExternalResultLedger(tmp_path / "external_results.jsonl")


def _adapter(tmp_path) -> ExternalOracleAdapter:
    return ExternalOracleAdapter(
        approvals_path=tmp_path / "approvals.jsonl",
        results_path=tmp_path / "external_results.jsonl",
    )


class _ExplodingSandbox:
    """A sandbox that fails loudly if the external adapter ever tries to run anything."""

    def __getattr__(self, name):  # pragma: no cover - only hit on a boundary violation
        raise AssertionError(f"external adapter must not use the execution plane (called {name!r})")


def _approve(gate, task, candidate="compound-A", *, by="dr-ruth"):
    spec = external_spec_for(task, candidate)
    req = propose_external_experiment(gate, spec, actor="agent:hypothesis")
    gate.approve(req.request_id, by=by)
    return spec, req


# --------------------------------------------------------------------------- #
# propose / approve bounds.
# --------------------------------------------------------------------------- #


def test_propose_records_pending_external_request(tmp_path):
    gate = _gate(tmp_path)
    spec = external_spec_for(_task(), "compound-A")
    req = propose_external_experiment(gate, spec, actor="agent:hypothesis")
    assert req.action is GovernedAction.EXTERNAL_EXPERIMENT
    assert req.content_hash == spec_content_hash(spec)
    assert gate.status_of(req.request_id) == "pending"


def test_agent_cannot_self_approve(tmp_path):
    gate = _gate(tmp_path)
    spec = external_spec_for(_task(), "compound-A")
    req = propose_external_experiment(gate, spec, actor="agent:hypothesis")
    with pytest.raises(ValueError):
        gate.approve(req.request_id, by="agent:hypothesis")
    assert gate.status_of(req.request_id) == "pending"


# --------------------------------------------------------------------------- #
# happy path: propose -> approve -> ingest -> adapter promotes.
# --------------------------------------------------------------------------- #


def test_ingested_signed_result_promotes_only_when_bound(tmp_path):
    gate = _gate(tmp_path)
    results = _results(tmp_path)
    task = _task()
    spec, req = _approve(gate, task)

    record = ingest_external_result(
        gate,
        results,
        req.request_id,
        primary=0.92,
        passed=True,
        operator_id="dr-ruth",
        provenance="lab-notebook-42",
        signing_key=SIGNING_KEY,
    )
    assert record.signature_verified
    assert record.content_hash == spec_content_hash(spec)

    metric = _adapter(tmp_path).evaluate(task, "compound-A", _ExplodingSandbox())
    assert metric.passed and metric.reproducible
    assert metric.primary == pytest.approx(0.92)

    baseline = metric.model_copy(update={"primary": 0.5})
    improved, _ = research_improves(metric, baseline, regime=EvaluatorRegime.EXTERNAL_ORACLE)
    assert improved


def test_adapter_awaits_when_no_result_ingested(tmp_path):
    gate = _gate(tmp_path)
    task = _task()
    _approve(gate, task)  # approved, but nothing ingested yet
    metric = _adapter(tmp_path).evaluate(task, "compound-A", _ExplodingSandbox())
    assert not metric.passed
    assert not metric.reproducible
    assert "awaiting" in metric.error


# --------------------------------------------------------------------------- #
# rejection bounds (rejected AND logged).
# --------------------------------------------------------------------------- #


def test_unapproved_result_is_rejected_and_logged(tmp_path):
    gate = _gate(tmp_path)
    results = _results(tmp_path)
    task = _task()
    spec = external_spec_for(task, "compound-A")
    req = propose_external_experiment(gate, spec, actor="agent:hypothesis")
    # No approval recorded.
    with pytest.raises(ExternalResultRejected):
        ingest_external_result(
            gate,
            results,
            req.request_id,
            primary=0.9,
            operator_id="dr-ruth",
            signing_key=SIGNING_KEY,
        )
    logged = results.records()
    assert len(logged) == 1
    assert logged[0].status is ExternalResultStatus.REJECTED


def test_agent_operator_cannot_attest_result(tmp_path):
    gate = _gate(tmp_path)
    results = _results(tmp_path)
    task = _task()
    _, req = _approve(gate, task)
    with pytest.raises(ExternalResultRejected):
        ingest_external_result(
            gate,
            results,
            req.request_id,
            primary=0.9,
            operator_id="agent:eval",
            signing_key=SIGNING_KEY,
        )
    assert results.records()[0].status is ExternalResultStatus.REJECTED


def test_unsigned_result_is_rejected(tmp_path):
    gate = _gate(tmp_path)
    results = _results(tmp_path)
    task = _task()
    _, req = _approve(gate, task)
    with pytest.raises(ExternalResultRejected):
        ingest_external_result(gate, results, req.request_id, primary=0.9, operator_id="dr-ruth")
    assert results.records()[0].status is ExternalResultStatus.REJECTED


def test_result_for_one_candidate_does_not_satisfy_another(tmp_path):
    gate = _gate(tmp_path)
    results = _results(tmp_path)
    task = _task()
    _, req = _approve(gate, task, candidate="compound-A")
    ingest_external_result(
        gate,
        results,
        req.request_id,
        primary=0.95,
        passed=True,
        operator_id="dr-ruth",
        signing_key=SIGNING_KEY,
    )
    # The approved + ingested result is for compound-A; a different candidate has a different
    # content hash and cannot resolve it.
    metric = _adapter(tmp_path).evaluate(task, "compound-B", _ExplodingSandbox())
    assert not metric.passed and not metric.reproducible


def test_revoked_approval_unpromotes_after_ingest(tmp_path):
    gate = _gate(tmp_path)
    results = _results(tmp_path)
    task = _task()
    spec, req = _approve(gate, task)
    ingest_external_result(
        gate,
        results,
        req.request_id,
        primary=0.95,
        passed=True,
        operator_id="dr-ruth",
        signing_key=SIGNING_KEY,
    )
    decision = gate.authorize(GovernedAction.EXTERNAL_EXPERIMENT, req.target, payload=req.payload)
    gate.revoke(decision.decision_id, by="dr-ruth", reason="contamination found")
    assert resolve_external_result(gate, results, spec) is None
    metric = _adapter(tmp_path).evaluate(task, "compound-A", _ExplodingSandbox())
    assert not metric.passed and not metric.reproducible


# --------------------------------------------------------------------------- #
# negative / null results are first-class.
# --------------------------------------------------------------------------- #


def test_null_result_is_archived_with_reason_and_never_promotes(tmp_path):
    gate = _gate(tmp_path)
    results = _results(tmp_path)
    task = _task()
    _, req = _approve(gate, task)
    record = ingest_external_result(
        gate,
        results,
        req.request_id,
        status=ExternalResultStatus.NULL,
        passed=False,
        operator_id="dr-ruth",
        reason="assay inconclusive — sample degraded",
        signing_key=SIGNING_KEY,
    )
    assert record.status is ExternalResultStatus.NULL
    assert "inconclusive" in record.reason
    metric = _adapter(tmp_path).evaluate(task, "compound-A", _ExplodingSandbox())
    assert not metric.passed  # a null result can never satisfy the precondition
    # It is still on the ledger — negative data is not discarded.
    assert any(r.status is ExternalResultStatus.NULL for r in results.records())


# --------------------------------------------------------------------------- #
# plane isolation: the adapter never touches the execution plane.
# --------------------------------------------------------------------------- #


def test_adapter_never_uses_execution_plane(tmp_path):
    gate = _gate(tmp_path)
    results = _results(tmp_path)
    task = _task()
    _, req = _approve(gate, task)
    ingest_external_result(
        gate,
        results,
        req.request_id,
        primary=0.9,
        passed=True,
        operator_id="dr-ruth",
        signing_key=SIGNING_KEY,
    )
    # _ExplodingSandbox raises on any attribute access; a clean evaluate proves the adapter
    # ran no candidate code and reached no instrument/network through the sandbox.
    metric = _adapter(tmp_path).evaluate(task, "compound-A", _ExplodingSandbox())
    assert metric.passed
