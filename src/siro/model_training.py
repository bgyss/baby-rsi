"""Governed model-training (weight-update) experiments (Goal 12 — the strongest loop).

This is the most sensitive capability in the project: producing model *weights* that could
feed back into the organization ("better model → better researcher", ``docs/00_principles.md``).
It is available only through the bounded cycle of ``docs/13_self_improvement_loop.md`` and
carries the strictest gates:

- **Stability precondition first.** A weight-update run is refused unless the evaluator, audit
  ledger, and gates are green and stable — checked *before* and *independently of* any
  approval (``docs/00`` non-goal: "fine-tune model weights before the scaffold, evaluator,
  and audit systems are stable"). A regressed safety gate fails the precondition.
- **Governance-gated start.** Even when stable, a run needs a human-approved ``MODEL_TRAIN``
  governance request (Goal 10), bound to the exact ``(experiment, config)``.
- **Artifacts with lineage.** Produced weights are stored with full reproducible lineage
  (base-model hash, data id + seed, config, code version) and archived; failed runs too.
- **No auto-deploy.** A trained model is **never** bound to an agent role automatically.
  :func:`deploy_model` requires a *separate* ``MODEL_DEPLOY`` approval **and** cross-model
  review (the reviewer's provider differs from the role's implementation provider).
- **Offline + objective.** Training is controller-owned, deterministic, pure-Python (no
  network, no credentials); a held-out metric decides quality, reproducibly — never
  self-judgment. Disabled entirely at Tier ≤ 1 (config-only to lower).
"""

from __future__ import annotations

import hashlib
import math
import random
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .archive import DEFAULT_MODEL_CALLS_PATH
from .governance import GovernanceGate
from .schemas import (
    GateDecision,
    GovernedAction,
    ModelDeployment,
    TrainedModelArtifact,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .scale import ComputeBudget

DEFAULT_MODEL_ARTIFACTS_PATH = Path("runs/model_artifacts.jsonl")
DEFAULT_ARTIFACT_STORE_DIR = Path("runs/artifacts/models")
DEFAULT_MODEL_REGISTRY_PATH = Path("runs/model_registry.jsonl")

#: Fixed, candidate-immutable training/validation data identity (mirrors Goal 06): the data
#: lives here, never in the train config, so a lower loss can't come from changed data.
DATA_ID = "governed-binary-v1"
DATA_SEED = 91
#: Bumped when the trainer changes — part of an artifact's lineage.
CODE_VERSION = "goal12-trainer-1"
#: Held-out BCE below this counts as "learned something" (the pass precondition).
PASS_VAL_LOSS = 0.5


def _short_id() -> str:
    return uuid.uuid4().hex[:12]


# --------------------------------------------------------------------------- #
# Stability precondition.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class StabilityReport:
    """Whether the scaffold is stable enough to permit a weight-update run (Goal 12)."""

    stable: bool
    checks: dict[str, bool] = field(default_factory=dict)

    @property
    def failures(self) -> list[str]:
        return [name for name, ok in self.checks.items() if not ok]


def _gates_green() -> bool:
    """The safety gate still distinguishes safe from unsafe code (a real "gates green" check)."""
    from .gates import safety_gate

    clean = safety_gate("def f():\n    return 1\n").decision is GateDecision.PASSED
    flags = safety_gate("import socket\n").decision is not GateDecision.PASSED
    return clean and flags


def _evaluator_present() -> bool:
    try:
        from .evaluator import evaluate  # noqa: F401 - import is the check
    except Exception:  # pragma: no cover - defensive
        return False
    return True


def _audit_ready(path: Path) -> bool:
    """The audit ledger directory is present/creatable — logging is not disabled."""
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    except OSError:  # pragma: no cover - defensive
        return False
    return True


def assess_stability(
    *, audit_ledger_path: str | Path = DEFAULT_MODEL_CALLS_PATH, open_incidents: int = 0
) -> StabilityReport:
    """Assess whether weight-update experiments may run (evaluator/audit/gates green)."""
    checks = {
        "gates_green": _gates_green(),
        "evaluator_present": _evaluator_present(),
        "audit_ledger_ready": _audit_ready(Path(audit_ledger_path)),
        "no_open_incidents": open_incidents == 0,
    }
    return StabilityReport(stable=all(checks.values()), checks=checks)


# --------------------------------------------------------------------------- #
# The deterministic, controller-owned trainer (the weights are the artifact).
# --------------------------------------------------------------------------- #


def _make_data() -> tuple[list, list]:
    """Fixed two-blob binary problem; first 60/class train, last 20/class validate."""
    rng = random.Random(DATA_SEED)
    train, val = [], []
    for c in (0, 1):
        cx = -1.5 if c == 0 else 1.5
        for i in range(80):
            point = [cx + rng.gauss(0.0, 1.0), rng.gauss(0.0, 1.0)]
            (train if i < 60 else val).append((point, c))
    return train, val


def _sigmoid(z: float) -> float:
    if z < -60:
        return 0.0
    if z > 60:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))


def _bce(data: list, w: list[float], b: float) -> float:
    total = 0.0
    for x, y in data:
        p = min(max(_sigmoid(w[0] * x[0] + w[1] * x[1] + b), 1e-12), 1 - 1e-12)
        total += -(y * math.log(p) + (1 - y) * math.log(1 - p))
    return total / len(data)


def base_model_hash() -> str:
    """Hash of the (fixed, zero) base model the training starts from — lineage anchor."""
    return hashlib.sha256(b"linear-2-1:zeros").hexdigest()[:16]


def train_weights(config: dict, *, wall_clock_seconds: float = 10.0) -> tuple[list[float], float, bool]:
    """Train a tiny logistic-regression model deterministically; return (weights, val_loss, passed).

    Zero-initialized and full-batch, so the result is bit-identical across reruns (the
    reproducibility the gate requires). The wall-clock budget is a cooperative cap (a
    too-small budget stops early and likely fails the pass precondition).
    """
    lr = float(config.get("learning_rate", 0.1))
    epochs = int(config.get("epochs", 300))
    train, val = _make_data()
    w = [0.0, 0.0]
    b = 0.0
    n = len(train)
    start = time.perf_counter()
    for _ in range(epochs):
        if time.perf_counter() - start >= wall_clock_seconds:
            break
        gw = [0.0, 0.0]
        gb = 0.0
        for x, y in train:
            d = _sigmoid(w[0] * x[0] + w[1] * x[1] + b) - y
            gw[0] += d * x[0]
            gw[1] += d * x[1]
            gb += d
        w[0] -= lr * gw[0] / n
        w[1] -= lr * gw[1] / n
        b -= lr * gb / n
    val_loss = _bce(val, w, b)
    passed = math.isfinite(val_loss) and val_loss < PASS_VAL_LOSS
    return [w[0], w[1], b], val_loss, passed


# --------------------------------------------------------------------------- #
# Artifact store + archive.
# --------------------------------------------------------------------------- #


def _read_lines(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if line:
                yield line


class ArtifactStore:
    """Per-artifact JSON store under ``runs/artifacts/models/`` (the weights + lineage)."""

    def __init__(self, directory: str | Path = DEFAULT_ARTIFACT_STORE_DIR) -> None:
        self.directory = Path(directory)

    def save(self, artifact: TrainedModelArtifact) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{artifact.artifact_id}.json"
        path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load(self, artifact_id: str) -> TrainedModelArtifact | None:
        path = self.directory / f"{artifact_id}.json"
        if not path.exists():
            return None
        return TrainedModelArtifact.model_validate_json(path.read_text(encoding="utf-8"))


class ModelArtifactArchive:
    """Append-only archive of every trained-model artifact (negatives included)."""

    def __init__(self, path: str | Path = DEFAULT_MODEL_ARTIFACTS_PATH) -> None:
        self.path = Path(path)

    def append(self, artifact: TrainedModelArtifact) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(artifact.model_dump_json() + "\n")

    def read_all(self) -> list[TrainedModelArtifact]:
        return [TrainedModelArtifact.model_validate_json(line) for line in _read_lines(self.path)]


# --------------------------------------------------------------------------- #
# The governed trainer + the gated deploy.
# --------------------------------------------------------------------------- #


class ModelTrainingDisabled(RuntimeError):
    """Raised when a weight-update run is attempted below Tier 2 (the capability is off)."""


class StabilityError(RuntimeError):
    """Raised when the stability precondition is not met (refused independent of approval)."""


class DeploymentError(RuntimeError):
    """Raised when a deploy violates cross-model review."""


class GovernedModelTrainer:
    """Runs a weight-update experiment behind the stability + governance gates (Goal 12)."""

    def __init__(
        self,
        gate: GovernanceGate,
        *,
        archive: ModelArtifactArchive | None = None,
        store: ArtifactStore | None = None,
        tiers: "dict[int, ComputeBudget] | None" = None,
    ) -> None:
        from .scale import DEFAULT_COMPUTE_TIERS

        self.gate = gate
        self.archive = archive or ModelArtifactArchive()
        self.store = store or ArtifactStore()
        self.tiers = tiers or dict(DEFAULT_COMPUTE_TIERS)

    def train(
        self,
        experiment_id: str,
        train_config: dict,
        *,
        compute_tier: int = 0,
        actor: str = "",
        rationale: str = "",
        stability: StabilityReport | None = None,
    ) -> TrainedModelArtifact:
        """Produce a model-weight artifact, gated by stability + governance.

        Refuses (raising, never silently proceeding) if the capability is disabled below Tier
        2, if the stability precondition is unmet (independent of any approval), or if no
        ``MODEL_TRAIN`` approval is on record. On success the weights + full lineage are stored
        and archived; a non-passing run is archived too (negative results are first-class).
        """
        if not self.gate.enabled:
            raise ModelTrainingDisabled(
                "model-training is a Tier 2 capability; the governance gate is disabled at this "
                "tier (config-only to enable)."
            )
        report = stability or assess_stability()
        if not report.stable:
            raise StabilityError(
                f"stability precondition not met: {report.failures}. Weight-update experiments "
                "are refused until the evaluator/audit/gates are green — independent of approval."
            )
        # Governance approval bound to the exact (experiment, config). Default-deny.
        self.gate.require(
            GovernedAction.MODEL_TRAIN,
            target=f"train:{experiment_id}",
            payload={"train_config": train_config, "compute_tier": compute_tier},
            actor=actor,
            rationale=rationale or f"weight-update experiment {experiment_id}",
        )
        budget = self.tiers.get(compute_tier)
        wall_clock = budget.wall_clock_seconds if budget is not None else 10.0
        weights, val_loss, passed = train_weights(train_config, wall_clock_seconds=wall_clock)
        artifact = TrainedModelArtifact(
            artifact_id=_short_id(),
            experiment_id=experiment_id,
            base_model_hash=base_model_hash(),
            data_id=DATA_ID,
            data_seed=DATA_SEED,
            train_config=train_config,
            code_version=CODE_VERSION,
            weights=weights,
            val_loss=val_loss,
            passed=passed,
            reason=f"val_loss={val_loss:g} passed={passed}",
        )
        self.store.save(artifact)
        self.archive.append(artifact)
        return artifact


class ModelRegistry:
    """Append-only record of which trained artifacts are bound to which agent roles (Goal 12)."""

    def __init__(self, path: str | Path = DEFAULT_MODEL_REGISTRY_PATH) -> None:
        self.path = Path(path)

    def append(self, deployment: ModelDeployment) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(deployment.model_dump_json() + "\n")

    def deployments(self) -> list[ModelDeployment]:
        return [ModelDeployment.model_validate_json(line) for line in _read_lines(self.path)]

    def is_deployed(self, artifact_id: str, role: str) -> bool:
        return any(d.artifact_id == artifact_id and d.role == role for d in self.deployments())


def deploy_model(
    gate: GovernanceGate,
    registry: ModelRegistry,
    artifact: TrainedModelArtifact,
    role: str,
    *,
    implementation_provider: str,
    reviewer_provider: str,
    actor: str = "",
) -> ModelDeployment:
    """Bind a trained artifact to an agent role — only with approval + cross-model review.

    Refuses (raising) unless the reviewer's provider differs from the role's implementation
    provider (cross-model review) **and** a human-approved ``MODEL_DEPLOY`` request bound to
    this exact ``(artifact, role)`` is on record. Nothing else can bind a trained model to a
    role, so a model never reaches the org on the loop's own authority.
    """
    if reviewer_provider == implementation_provider:
        raise DeploymentError(
            "cross-model review required: the reviewer provider must differ from the role's "
            f"implementation provider (both {implementation_provider!r})."
        )
    decision = gate.require(
        GovernedAction.MODEL_DEPLOY,
        target=f"deploy:{role}",
        payload={"artifact_id": artifact.artifact_id, "role": role},
        actor=actor,
        rationale=f"deploy {artifact.artifact_id} to role {role}",
    )
    deployment = ModelDeployment(
        deployment_id=_short_id(),
        artifact_id=artifact.artifact_id,
        role=role,
        approver=decision.approver,
        reviewer_provider=reviewer_provider,
        implementation_provider=implementation_provider,
    )
    registry.append(deployment)
    return deployment


__all__ = [
    "DEFAULT_MODEL_ARTIFACTS_PATH",
    "DEFAULT_ARTIFACT_STORE_DIR",
    "DEFAULT_MODEL_REGISTRY_PATH",
    "DATA_ID",
    "DATA_SEED",
    "CODE_VERSION",
    "StabilityReport",
    "assess_stability",
    "base_model_hash",
    "train_weights",
    "ArtifactStore",
    "ModelArtifactArchive",
    "ModelTrainingDisabled",
    "StabilityError",
    "DeploymentError",
    "GovernedModelTrainer",
    "ModelRegistry",
    "deploy_model",
]
