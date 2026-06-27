"""Governed external-experiment boundary (Goal 26).

A *Regime-C* science (``docs/18_generalizing_to_sciences.md``) grounds its metric in a
real-world action — a wet-lab assay, a fabrication run, instrument time, paid HPC — that the
execution plane must never reach. This module makes such an experiment a
:class:`~siro.schemas.GovernedAction` (``EXTERNAL_EXPERIMENT``) and gives it a
``propose → approve → execute → ingest`` lifecycle on top of the existing Tier-2 governance
machinery (Goals 10/11/19):

- **propose** — the org emits a typed :class:`~siro.schemas.ExternalExperimentSpec` as an
  ``EXTERNAL_EXPERIMENT`` approval request. No agent tool authorizes it.
- **approve** — a human approves through the existing :class:`~siro.governance.GovernanceGate`
  (default-deny, identity/two-person rules, expiry, revocation).
- **execute** — a human, or an instrument under human authority, performs the action
  **outside** ``siro``. The execution plane runs no part of it and holds no credentials.
- **ingest** — the operator returns a *signed result record* bound to the approved action
  hash; the controller validates the binding and ingests it as the candidate's metric.

The :class:`ExternalOracleAdapter` is the Goal-22 evaluator adapter for this regime: instead
of running candidate code it resolves the signed, approved result for the candidate and
returns its :class:`~siro.schemas.MetricRecord`. Promotion is still decided by that objective
metric, never by model judgment, and an unbound/expired/revoked result never promotes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .governance import ApprovalLedger, GovernanceGate, governed_action_hash
from .packs import EvaluatorRegime
from .schemas import (
    ApprovalRequest,
    ExternalExperimentClass,
    ExternalExperimentSpec,
    ExternalResultRecord,
    ExternalResultStatus,
    GovernedAction,
    MetricRecord,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .research import ResearchTask
    from .sandbox import Sandbox

DEFAULT_EXTERNAL_RESULTS_PATH = Path("runs/external_results.jsonl")


def _short_id() -> str:
    return uuid.uuid4().hex[:12]


def _candidate_hash(candidate_code: str) -> str:
    return hashlib.sha256(candidate_code.encode("utf-8")).hexdigest()


def _canonical_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


# --------------------------------------------------------------------------- #
# Spec / binding — deterministic so the proposer and the adapter agree.
# --------------------------------------------------------------------------- #


def external_spec_for(task: "ResearchTask", candidate_code: str) -> ExternalExperimentSpec:
    """Build the typed external-experiment spec for a (task, candidate) deterministically.

    The proposer and the evaluator adapter both call this so they compute the *same*
    ``content_hash``: an approval is bound to the exact candidate (via ``candidate_hash``) and
    the exact measurement. The external metadata (action class, cost/risk envelope) is read
    from the controller-owned ``task.json`` ``external`` block; a candidate cannot set it.
    """
    meta = getattr(task, "external", None) or {}
    action_class = ExternalExperimentClass(meta.get("action_class", "assay"))
    return ExternalExperimentSpec(
        action_class=action_class,
        task_id=task.task_id,
        candidate_hash=_candidate_hash(candidate_code),
        proposal=meta.get("proposal", f"measure {task.primary_name} for {task.task_id}"),
        measurement=meta.get("measurement", task.primary_name),
        primary_name=task.primary_name,
        higher_is_better=task.higher_is_better,
        secondary_names=list(meta.get("secondary_names", [])),
        cost_usd=float(meta.get("cost_usd", 0.0)),
        cost_note=str(meta.get("cost_note", "")),
        risk=str(meta.get("risk", "high")),
        irreversible=bool(meta.get("irreversible", True)),
    )


def spec_target(spec: ExternalExperimentSpec) -> str:
    return spec.task_id


def spec_payload(spec: ExternalExperimentSpec) -> dict:
    return spec.model_dump(mode="json")


def spec_content_hash(spec: ExternalExperimentSpec) -> str:
    """Content hash binding an approval to this exact proposal."""
    return governed_action_hash(
        GovernedAction.EXTERNAL_EXPERIMENT, spec_target(spec), spec_payload(spec)
    )


# --------------------------------------------------------------------------- #
# Signing — a local HMAC proof the operator attaches to a result (dev adapter).
# --------------------------------------------------------------------------- #


def canonical_result_payload(record: ExternalResultRecord) -> dict:
    """Canonical payload an operator signs for one ingested result."""
    return {
        "action": GovernedAction.EXTERNAL_EXPERIMENT.value,
        "content_hash": record.content_hash,
        "operator_id": record.operator_id,
        "primary": record.primary,
        "primary_name": record.primary_name,
        "request_id": record.request_id,
        "status": record.status.value,
    }


def result_payload_hash(record: ExternalResultRecord) -> str:
    return hashlib.sha256(
        _canonical_json(canonical_result_payload(record)).encode("utf-8")
    ).hexdigest()


def result_signing_proof(record: ExternalResultRecord, signing_key: str) -> str:
    """Local HMAC signing proof for development; the key is never written to the ledger."""
    return hmac.new(
        signing_key.encode("utf-8"),
        result_payload_hash(record).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


# --------------------------------------------------------------------------- #
# Result ledger — append-only, alongside the approval ledger.
# --------------------------------------------------------------------------- #


def _read_lines(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if line:
                yield line


class ExternalResultLedger:
    """Append-only ledger of ingested external results (and logged rejections)."""

    def __init__(self, path: str | Path = DEFAULT_EXTERNAL_RESULTS_PATH) -> None:
        self.path = Path(path)

    def append(self, record: ExternalResultRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(record.model_dump_json() + "\n")

    def records(self) -> list[ExternalResultRecord]:
        return [ExternalResultRecord.model_validate_json(line) for line in _read_lines(self.path)]

    def for_request(self, request_id: str) -> list[ExternalResultRecord]:
        return [r for r in self.records() if r.request_id == request_id]

    def for_content_hash(self, content_hash: str) -> list[ExternalResultRecord]:
        return [r for r in self.records() if r.content_hash == content_hash]


class ExternalResultRejected(RuntimeError):
    """Raised when an ingested result does not bind to a live, matching approval.

    The rejected attempt is still logged to the result ledger (``status=REJECTED``) so the
    audit trail records every attempt, including spoofed or stale ones.
    """

    def __init__(self, record: ExternalResultRecord, reason: str) -> None:
        super().__init__(f"external result rejected: {reason}")
        self.record = record
        self.reason = reason


# --------------------------------------------------------------------------- #
# Lifecycle — propose / ingest / resolve.
# --------------------------------------------------------------------------- #


def propose_external_experiment(
    gate: GovernanceGate,
    spec: ExternalExperimentSpec,
    *,
    actor: str = "",
    rationale: str = "",
    rollback_plan: str = "",
    evidence: list[str] | None = None,
) -> ApprovalRequest:
    """Record an ``EXTERNAL_EXPERIMENT`` approval request (propose step).

    Agents (and the controller) may *propose*; no tool here approves. The request is
    default-deny until a human decides. External actions are treated as high-risk /
    irreversible and inherit the Goal 11 promotion-before-budget and Goal 19 identity rules
    enforced by the gate at approval time.
    """
    return gate.request(
        GovernedAction.EXTERNAL_EXPERIMENT,
        spec_target(spec),
        actor=actor,
        rationale=rationale,
        payload=spec_payload(spec),
        risk=spec.risk,
        evidence=evidence or [],
        rollback_plan=rollback_plan,
    )


def ingest_external_result(
    gate: GovernanceGate,
    results: ExternalResultLedger,
    request_id: str,
    *,
    status: ExternalResultStatus = ExternalResultStatus.OK,
    primary: float = 0.0,
    passed: bool = True,
    secondary: dict[str, float] | None = None,
    operator_id: str,
    provenance: str = "",
    reason: str = "",
    signature: str = "",
    signing_key: str | None = None,
) -> ExternalResultRecord:
    """Validate and ingest a signed external result, binding it to a live approval.

    The result is accepted only if it binds to a live, granted approval for the exact
    proposal: the request exists, its decision is granted-and-not-expired-and-not-revoked, the
    operator is a real human id, and the signature (or local signing proof) verifies. An
    unapproved, expired, revoked, hash-mismatched, or unsigned result is logged with
    ``status=REJECTED`` and raises :class:`ExternalResultRejected` — it never promotes.
    """
    req = gate.ledger.request(request_id)
    base = ExternalResultRecord(
        result_id=_short_id(),
        request_id=request_id,
        content_hash=req.content_hash if req else "",
        action_class=ExternalExperimentClass(
            (req.payload.get("action_class") if req else None) or "assay"
        ),
        status=status,
        primary=primary,
        passed=passed,
        secondary=dict(secondary or {}),
        operator_id=operator_id,
        provenance=provenance,
        reason=reason,
    )
    if req is not None:
        base.primary_name = str(req.payload.get("primary_name", "primary"))
        base.higher_is_better = bool(req.payload.get("higher_is_better", True))

    def _reject(why: str) -> "ExternalResultRecord":
        rejected = base.model_copy(
            update={"status": ExternalResultStatus.REJECTED, "reason": why, "passed": False}
        )
        results.append(rejected)
        raise ExternalResultRejected(rejected, why)

    if req is None:
        _reject(f"no approval request {request_id!r} on record")
    if not operator_id or operator_id.startswith("agent:"):
        _reject("an external result requires a real human operator id (agents cannot attest)")

    # The approval must be live (granted, unexpired, unrevoked) and bound to this exact proposal.
    decision = gate.authorize(
        GovernedAction.EXTERNAL_EXPERIMENT,
        req.target,
        payload=req.payload,
        consume=False,
    )
    if decision is None:
        _reject(
            f"no live approval for request {request_id!r} "
            f"(status {gate.status_of(request_id)!r}); default-deny"
        )
    if decision.content_hash != req.content_hash:
        _reject("approval content hash does not match the request (hash mismatch)")

    base.decision_id = decision.decision_id
    payload_hash = result_payload_hash(base)
    if signing_key:
        signature = result_signing_proof(base, signing_key)
    verified = bool(signature)
    if signing_key:
        verified = hmac.compare_digest(signature, result_signing_proof(base, signing_key))
    if not verified:
        _reject("result is missing a valid signature / signing proof")

    record = base.model_copy(
        update={
            "signature": signature,
            "signature_payload_hash": payload_hash,
            "signature_verified": True,
        }
    )
    results.append(record)
    return record


def resolve_external_result(
    gate: GovernanceGate,
    results: ExternalResultLedger,
    spec: ExternalExperimentSpec,
) -> ExternalResultRecord | None:
    """Return the live, accepted, signed result bound to ``spec``'s approval, or ``None``.

    Re-checks liveness at read time: a result whose approval was revoked or expired after
    ingest no longer resolves, so a candidate it once authorized stops being promotable.
    """
    content_hash = spec_content_hash(spec)
    decision = gate.authorize(
        GovernedAction.EXTERNAL_EXPERIMENT,
        spec_target(spec),
        payload=spec_payload(spec),
        consume=False,
    )
    if decision is None:
        return None
    accepted = [
        r
        for r in results.for_content_hash(content_hash)
        if r.status is not ExternalResultStatus.REJECTED and r.signature_verified
    ]
    if not accepted:
        return None
    return max(accepted, key=lambda r: r.created_at)


# --------------------------------------------------------------------------- #
# Regime-C evaluator adapter (Goal 22).
# --------------------------------------------------------------------------- #


@dataclass
class ExternalOracleAdapter:
    """Evaluator adapter that scores on an ingested, approved, signed external result.

    It runs **no candidate code** and touches **no network or instrument** — it only reads the
    control-plane approval and result ledgers. If no live, matching, signed result exists, it
    returns a non-passing, non-reproducible metric so the candidate cannot promote (the boundary
    is default-deny: an experiment is "awaiting" until a human ingests its result).
    """

    regime: EvaluatorRegime = EvaluatorRegime.EXTERNAL_ORACLE
    approvals_path: str | Path = ApprovalLedger().path
    results_path: str | Path = DEFAULT_EXTERNAL_RESULTS_PATH

    def evaluate(
        self,
        task: "ResearchTask",
        candidate_code: str,
        sandbox: "Sandbox",
        *,
        seed: int | None = None,
    ) -> MetricRecord:
        gate = GovernanceGate(ApprovalLedger(self.approvals_path))
        results = ExternalResultLedger(self.results_path)
        spec = external_spec_for(task, candidate_code)
        record = resolve_external_result(gate, results, spec)
        if record is None:
            return MetricRecord(
                primary_name=spec.primary_name,
                higher_is_better=spec.higher_is_better,
                passed=False,
                reproducible=False,
                error="awaiting a live, approved, signed external result",
            )
        return record.to_metric()


__all__ = [
    "DEFAULT_EXTERNAL_RESULTS_PATH",
    "external_spec_for",
    "spec_target",
    "spec_payload",
    "spec_content_hash",
    "canonical_result_payload",
    "result_payload_hash",
    "result_signing_proof",
    "ExternalResultLedger",
    "ExternalResultRejected",
    "propose_external_experiment",
    "ingest_external_result",
    "resolve_external_result",
    "ExternalOracleAdapter",
]
