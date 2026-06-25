"""Goal 12 — governed model-training: stability + governance gates, lineage, no auto-deploy.

All offline and deterministic. The weight-update capability is reachable only at Tier 2,
only when the scaffold is stable, only with a human approval; a trained model never reaches
a role without a separate approval + cross-model review.
"""

from __future__ import annotations

import pytest

from siro.config import load_config
from siro.governance import ApprovalLedger, GovernanceDenied, GovernanceGate
from siro.model_training import (
    ArtifactStore,
    DeploymentError,
    GovernedModelTrainer,
    ModelArtifactArchive,
    ModelRegistry,
    ModelTrainingDisabled,
    StabilityError,
    StabilityReport,
    assess_stability,
    deploy_model,
    train_weights,
)
from siro.schemas import GovernedAction


def _enabled_gate(tmp_path):
    return GovernanceGate(ApprovalLedger(tmp_path / "approvals.jsonl"), enabled=True)


def _trainer(tmp_path, gate):
    return GovernedModelTrainer(
        gate,
        archive=ModelArtifactArchive(tmp_path / "artifacts.jsonl"),
        store=ArtifactStore(tmp_path / "store"),
    )


GOOD_CFG = {"learning_rate": 0.1, "epochs": 300}


def _approve_then(gate, fn):
    """Run ``fn``; on the first governance denial approve the recorded request and retry."""
    try:
        return fn()
    except GovernanceDenied as exc:
        gate.approve(exc.request.request_id, by="alice")
        return fn()


# --- disabled below Tier 2 --------------------------------------------------


def test_training_disabled_below_tier_2(tmp_path):
    gate = GovernanceGate.from_config(load_config("config/tier1.frontier.yaml"))
    trainer = _trainer(tmp_path, gate)
    with pytest.raises(ModelTrainingDisabled):
        trainer.train("exp", GOOD_CFG)


def test_training_enabled_at_tier_2_by_config():
    gate = GovernanceGate.from_config(load_config("config/tier2.governed.yaml"))
    assert gate.enabled is True


# --- stability precondition (independent of approval) -----------------------


def test_assess_stability_green_in_repo_and_red_on_incidents():
    assert assess_stability().stable is True
    report = assess_stability(open_incidents=1)
    assert report.stable is False and "no_open_incidents" in report.failures


def test_training_refused_when_unstable_even_with_approval(tmp_path):
    gate = _enabled_gate(tmp_path)
    trainer = _trainer(tmp_path, gate)
    unstable = StabilityReport(stable=False, checks={"gates_green": False})
    # Pre-approve so we prove stability is checked *before and independent of* approval.
    req = gate.request(
        GovernedAction.MODEL_TRAIN,
        target="train:exp",
        payload={"train_config": GOOD_CFG, "compute_tier": 0},
    )
    gate.approve(req.request_id, by="alice")
    with pytest.raises(StabilityError):
        trainer.train("exp", GOOD_CFG, stability=unstable)


# --- governance-gated start -------------------------------------------------


def test_training_refused_without_approval(tmp_path):
    gate = _enabled_gate(tmp_path)
    trainer = _trainer(tmp_path, gate)
    with pytest.raises(GovernanceDenied) as exc:
        trainer.train("exp", GOOD_CFG)
    assert "train:exp" in exc.value.request.target
    # Nothing was produced on the denied run.
    assert ModelArtifactArchive(tmp_path / "artifacts.jsonl").read_all() == []


def test_training_succeeds_with_stability_and_approval(tmp_path):
    gate = _enabled_gate(tmp_path)
    trainer = _trainer(tmp_path, gate)
    artifact = _approve_then(gate, lambda: trainer.train("exp", GOOD_CFG))
    assert artifact.passed and artifact.weights and artifact.val_loss < 0.5
    # Full reproducible lineage is recorded.
    assert artifact.base_model_hash and artifact.data_id and artifact.data_seed
    assert artifact.code_version and artifact.train_config == GOOD_CFG
    # Stored as an artifact and archived.
    assert ArtifactStore(tmp_path / "store").load(artifact.artifact_id) is not None
    assert len(ModelArtifactArchive(tmp_path / "artifacts.jsonl").read_all()) == 1


def test_failed_training_is_archived_as_negative(tmp_path):
    gate = _enabled_gate(tmp_path)
    trainer = _trainer(tmp_path, gate)
    # An under-trained config does not pass, but is still archived (negatives are data).
    artifact = _approve_then(gate, lambda: trainer.train("exp", {"learning_rate": 1e-4, "epochs": 2}))
    assert artifact.passed is False
    assert len(ModelArtifactArchive(tmp_path / "artifacts.jsonl").read_all()) == 1


def test_weights_are_reproducible():
    w1, l1, _ = train_weights(GOOD_CFG)
    w2, l2, _ = train_weights(GOOD_CFG)
    assert w1 == w2 and l1 == l2


# --- no auto-deploy; deploy is separately gated -----------------------------


def test_trained_model_is_not_auto_deployed(tmp_path):
    gate = _enabled_gate(tmp_path)
    trainer = _trainer(tmp_path, gate)
    artifact = _approve_then(gate, lambda: trainer.train("exp", GOOD_CFG))
    registry = ModelRegistry(tmp_path / "registry.jsonl")
    # Training produced an artifact but bound it to no role.
    assert registry.is_deployed(artifact.artifact_id, "implementation") is False


def test_deploy_requires_cross_model_review(tmp_path):
    gate = _enabled_gate(tmp_path)
    artifact = _approve_then(gate, lambda: _trainer(tmp_path, gate).train("exp", GOOD_CFG))
    registry = ModelRegistry(tmp_path / "registry.jsonl")
    with pytest.raises(DeploymentError, match="cross-model"):
        deploy_model(
            gate, registry, artifact, "implementation",
            implementation_provider="anthropic", reviewer_provider="anthropic",
        )


def test_deploy_requires_governance_approval(tmp_path):
    gate = _enabled_gate(tmp_path)
    artifact = _approve_then(gate, lambda: _trainer(tmp_path, gate).train("exp", GOOD_CFG))
    registry = ModelRegistry(tmp_path / "registry.jsonl")
    # Cross-model review satisfied, but no MODEL_DEPLOY approval on record -> denied.
    with pytest.raises(GovernanceDenied):
        deploy_model(
            gate, registry, artifact, "implementation",
            implementation_provider="anthropic", reviewer_provider="openai",
        )


def test_deploy_records_binding_with_approval_and_cross_model(tmp_path):
    gate = _enabled_gate(tmp_path)
    artifact = _approve_then(gate, lambda: _trainer(tmp_path, gate).train("exp", GOOD_CFG))
    registry = ModelRegistry(tmp_path / "registry.jsonl")
    deployment = _approve_then(
        gate,
        lambda: deploy_model(
            gate, registry, artifact, "implementation",
            implementation_provider="anthropic", reviewer_provider="openai",
        ),
    )
    assert deployment.approver == "alice"
    assert deployment.reviewer_provider == "openai"
    assert registry.is_deployed(artifact.artifact_id, "implementation") is True
