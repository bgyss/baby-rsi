"""Governance gate and human-approval workflow.

Goal 10 made Tier 2 default-deny with a hash-bound approval ledger. Goal 19 hardens that
ledger into a local, production-shaped approval system: typed operators, policy templates,
signed approval proofs, two-person approval where required, packet export, and verification.
Old Goal 10 records remain readable; they are marked as legacy when inspected.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from .schemas import (
    ApprovalDecision,
    ApprovalRequest,
    ApprovalRevocation,
    ApprovalScope,
    GovernancePolicy,
    GovernedAction,
    OperatorIdentity,
    OperatorRole,
    OperatorStatus,
    _utcnow,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .config import SiroConfig

DEFAULT_APPROVALS_PATH = Path("runs/approvals.jsonl")
DEFAULT_OPERATORS_PATH = Path("runs/operators.jsonl")

GovernanceRecord = ApprovalRequest | ApprovalDecision | ApprovalRevocation


def _short_id() -> str:
    return uuid.uuid4().hex[:12]


def _canonical_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def governed_action_hash(action: GovernedAction, target: str, payload: dict | None) -> str:
    """Stable content hash over the exact proposed change."""
    return hashlib.sha256(
        _canonical_json(
            {"action": action.value, "target": target, "payload": payload or {}}
        ).encode("utf-8")
    ).hexdigest()


def canonical_approval_payload(request: ApprovalRequest, operator_id: str, granted: bool) -> dict:
    """Canonical payload an operator signs for one request decision."""
    return {
        "action": request.action.value,
        "content_hash": request.content_hash,
        "granted": granted,
        "operator_id": operator_id,
        "request_id": request.request_id,
        "scope": request.scope.value,
        "target": request.target,
    }


def approval_payload_hash(request: ApprovalRequest, operator_id: str, granted: bool = True) -> str:
    return hashlib.sha256(
        _canonical_json(canonical_approval_payload(request, operator_id, granted)).encode("utf-8")
    ).hexdigest()


def signing_proof(
    request: ApprovalRequest, operator_id: str, signing_key: str, granted: bool = True
) -> str:
    """Local HMAC signing proof for development.

    The signing key is supplied by the human-operated CLI or test harness and is never written
    to the ledger. External IdP signatures can later replace this adapter without changing the
    ledger fields.
    """
    return hmac.new(
        signing_key.encode("utf-8"),
        approval_payload_hash(request, operator_id, granted).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


class GovernanceDenied(RuntimeError):
    """Raised when a governed action is attempted without sufficient approval."""

    def __init__(self, request: ApprovalRequest, reason: str) -> None:
        super().__init__(f"governed action {request.action.value!r} denied: {reason}")
        self.request = request
        self.reason = reason


def _read_lines(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if line:
                yield line


class ApprovalLedger:
    """Append-only approval ledger."""

    def __init__(self, path: str | Path = DEFAULT_APPROVALS_PATH) -> None:
        self.path = Path(path)

    def append(self, record: GovernanceRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(record.model_dump_json() + "\n")

    @staticmethod
    def _parse(line: str) -> GovernanceRecord:
        tag = json.loads(line).get("record")
        if tag == "decision":
            return ApprovalDecision.model_validate_json(line)
        if tag == "revocation":
            return ApprovalRevocation.model_validate_json(line)
        return ApprovalRequest.model_validate_json(line)

    def read_all(self) -> list[GovernanceRecord]:
        return [self._parse(line) for line in _read_lines(self.path)]

    def requests(self) -> list[ApprovalRequest]:
        return [r for r in self.read_all() if isinstance(r, ApprovalRequest)]

    def decisions(self) -> list[ApprovalDecision]:
        return [r for r in self.read_all() if isinstance(r, ApprovalDecision)]

    def revocations(self) -> list[ApprovalRevocation]:
        return [r for r in self.read_all() if isinstance(r, ApprovalRevocation)]

    def request(self, request_id: str) -> ApprovalRequest | None:
        for req in self.requests():
            if req.request_id == request_id:
                return req
        return None


class OperatorLedger:
    """Append-only local operator identity registry."""

    def __init__(self, path: str | Path = DEFAULT_OPERATORS_PATH) -> None:
        self.path = Path(path)

    def append(self, identity: OperatorIdentity) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(identity.model_dump_json() + "\n")

    def identities(self) -> list[OperatorIdentity]:
        return [OperatorIdentity.model_validate_json(line) for line in _read_lines(self.path)]

    def latest(self) -> dict[str, OperatorIdentity]:
        latest: dict[str, OperatorIdentity] = {}
        for identity in self.identities():
            latest[identity.operator_id] = identity
        return latest

    def create(
        self,
        operator_id: str,
        *,
        display_name: str,
        role: OperatorRole,
        auth_method: str = "local",
        auth_metadata: dict[str, str] | None = None,
    ) -> OperatorIdentity:
        if operator_id in self.latest() and self.latest()[operator_id].active:
            raise ValueError(f"operator {operator_id!r} already exists and is active")
        identity = OperatorIdentity(
            operator_id=operator_id,
            display_name=display_name,
            role=role,
            auth_method=auth_method,
            auth_metadata=auth_metadata or {},
        )
        self.append(identity)
        return identity

    def revoke(self, operator_id: str) -> OperatorIdentity:
        current = self.latest().get(operator_id)
        if current is None:
            raise KeyError(f"unknown operator {operator_id!r}")
        revoked = current.model_copy(
            update={"status": OperatorStatus.REVOKED, "revoked_at": _utcnow()}
        )
        self.append(revoked)
        return revoked


@dataclass
class GovernanceVerification:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class GovernanceGate:
    """Default-deny gate with optional Goal 19 identity and policy hardening."""

    def __init__(
        self,
        ledger: ApprovalLedger | None = None,
        *,
        enabled: bool = True,
        operators: dict[str, OperatorIdentity] | None = None,
        policies: dict[GovernedAction, GovernancePolicy] | None = None,
        clock=_utcnow,
    ) -> None:
        self.ledger = ApprovalLedger() if ledger is None else ledger
        self.enabled = enabled
        self.operators = operators or {}
        self.policies = policies or {}
        self._clock = clock

    @classmethod
    def from_config(
        cls, config: "SiroConfig", *, ledger: ApprovalLedger | None = None
    ) -> "GovernanceGate":
        block = (config.raw.get("governance") or {}) if getattr(config, "raw", None) else {}
        path = block.get("approvals_path", DEFAULT_APPROVALS_PATH)
        enabled = config.tier >= 2 and bool(block.get("enabled", True))
        operators = {
            op["operator_id"]: OperatorIdentity.model_validate(op)
            for op in block.get("operators", [])
        }
        policies = {
            GovernancePolicy.model_validate(p).action: GovernancePolicy.model_validate(p)
            for p in block.get("policies", [])
        }
        return cls(
            ledger=ledger or ApprovalLedger(path),
            enabled=enabled,
            operators=operators,
            policies=policies,
        )

    # --- policy -------------------------------------------------------------
    def policy_for(self, action: GovernedAction) -> GovernancePolicy:
        return self.policies.get(
            action,
            GovernancePolicy(
                policy_id=f"default-{action.value}",
                action=action,
                required_reviewers=1,
                require_signature=bool(self.operators),
                max_scope=ApprovalScope.STANDING,
            ),
        )

    def _validate_operator(self, operator_id: str, policy: GovernancePolicy) -> OperatorIdentity:
        if not operator_id:
            raise ValueError(
                "an approval requires a human operator id (`by`); agents cannot approve."
            )
        if operator_id.startswith("agent:"):
            raise ValueError("agent identities cannot approve governed actions")
        if not self.operators:
            return OperatorIdentity(
                operator_id=operator_id,
                display_name=operator_id,
                role=OperatorRole.APPROVER,
                auth_method="legacy-local",
            )
        identity = self.operators.get(operator_id)
        if identity is None:
            raise ValueError(f"unknown operator {operator_id!r}")
        if not identity.active:
            raise ValueError(f"operator {operator_id!r} is inactive or revoked")
        allowed_roles = {policy.required_role, OperatorRole.ADMIN}
        if identity.role not in allowed_roles:
            raise ValueError(
                f"operator {operator_id!r} has role {identity.role.value!r}, "
                f"requires {policy.required_role.value!r}"
            )
        return identity

    def _validate_policy_request(self, req: ApprovalRequest, policy: GovernancePolicy) -> None:
        missing = [field for field in policy.required_rationale_fields if not req.rationale]
        if missing:
            raise ValueError(f"request {req.request_id} is missing required rationale")
        missing_evidence = [item for item in policy.required_evidence if item not in req.evidence]
        if missing_evidence:
            raise ValueError(
                f"request {req.request_id} is missing required evidence: {', '.join(missing_evidence)}"
            )
        if policy.max_scope is ApprovalScope.ONCE and req.scope is ApprovalScope.STANDING:
            raise ValueError(f"policy {policy.policy_id} does not allow standing approval scope")

    def _signed_decision(
        self,
        req: ApprovalRequest,
        *,
        operator_id: str,
        granted: bool,
        signature: str,
        signing_key: str | None,
        require_signature: bool,
    ) -> tuple[str, bool]:
        payload_hash = approval_payload_hash(req, operator_id, granted)
        if signing_key:
            signature = signing_proof(req, operator_id, signing_key, granted)
        verified = bool(signature)
        if signing_key:
            verified = hmac.compare_digest(
                signature, signing_proof(req, operator_id, signing_key, granted)
            )
        if require_signature and not verified:
            raise ValueError("policy requires a signature or local signing proof")
        return payload_hash, verified

    # --- request / authorization ------------------------------------------
    def request(
        self,
        action: GovernedAction,
        target: str = "",
        *,
        actor: str = "",
        rationale: str = "",
        payload: dict | None = None,
        risk: str = "medium",
        evidence: list[str] | None = None,
        rollback_plan: str = "",
        scope: ApprovalScope = ApprovalScope.ONCE,
        expires_at: datetime | None = None,
    ) -> ApprovalRequest:
        req = ApprovalRequest(
            request_id=_short_id(),
            action=action,
            target=target,
            content_hash=governed_action_hash(action, target, payload),
            actor=actor,
            rationale=rationale,
            payload=payload or {},
            risk=risk,
            evidence=evidence or [],
            rollback_plan=rollback_plan,
            scope=scope,
            expires_at=expires_at,
        )
        self.ledger.append(req)
        return req

    def _is_revoked(self, decision_id: str) -> bool:
        return any(rv.decision_id == decision_id for rv in self.ledger.revocations())

    def _valid_decisions(self, action: GovernedAction, content_hash: str) -> list[ApprovalDecision]:
        now = self._clock()
        decisions = [
            d
            for d in self.ledger.decisions()
            if d.granted
            and d.action is action
            and d.content_hash == content_hash
            and (d.expires_at is None or d.expires_at > now)
            and not self._is_revoked(d.decision_id)
        ]
        policy = self.policy_for(action)
        if not self.operators and not self.policies:
            return decisions
        return [
            d
            for d in decisions
            if d.operator_id
            and d.signature_verified
            and (not d.policy_id or d.policy_id == policy.policy_id)
            and self.operators.get(
                d.operator_id,
                OperatorIdentity(
                    operator_id=d.operator_id,
                    display_name=d.operator_id,
                    role=OperatorRole.APPROVER,
                ),
            ).active
        ]

    def authorize(
        self,
        action: GovernedAction,
        target: str = "",
        *,
        payload: dict | None = None,
        consume: bool = False,
    ) -> ApprovalDecision | None:
        content_hash = governed_action_hash(action, target, payload)
        decisions = self._valid_decisions(action, content_hash)
        policy = self.policy_for(action)
        operator_ids = {d.operator_id or d.approver for d in decisions}
        if len(operator_ids) < policy.required_reviewers:
            return None
        newest = max(decisions, key=lambda d: d.created_at)
        if consume:
            for decision in decisions:
                if decision.scope is ApprovalScope.ONCE:
                    self.revoke(
                        decision.decision_id, by="governance-gate", reason="consumed (single-use)"
                    )
        return newest

    def require(
        self,
        action: GovernedAction,
        target: str = "",
        *,
        actor: str = "",
        rationale: str = "",
        payload: dict | None = None,
        scope: ApprovalScope = ApprovalScope.ONCE,
        expires_at: datetime | None = None,
        consume: bool = True,
    ) -> ApprovalDecision:
        decision = self.authorize(action, target, payload=payload, consume=consume)
        if decision is not None:
            return decision
        req = self.request(
            action,
            target,
            actor=actor,
            rationale=rationale,
            payload=payload,
            scope=scope,
            expires_at=expires_at,
        )
        raise GovernanceDenied(req, "no matching approval on record (default-deny)")

    # --- human decisions ----------------------------------------------------
    def approve(
        self,
        request_id: str,
        *,
        by: str,
        scope: ApprovalScope | None = None,
        expires_at: datetime | None = None,
        reason: str = "",
        signature: str = "",
        signing_key: str | None = None,
    ) -> ApprovalDecision:
        req = self.ledger.request(request_id)
        if req is None:
            raise KeyError(f"no approval request {request_id!r} on record.")
        policy = self.policy_for(req.action)
        hardened = bool(self.operators or self.policies)
        self._validate_operator(by, policy)
        self._validate_policy_request(req, policy)
        if policy.separation_of_duties and req.actor == by:
            raise ValueError("requester and approver must be distinct for this policy")
        chosen_scope = scope or req.scope
        if policy.max_scope is ApprovalScope.ONCE and chosen_scope is ApprovalScope.STANDING:
            raise ValueError(f"policy {policy.policy_id} does not allow standing approval scope")
        if expires_at and policy.max_expiry_seconds is not None:
            if expires_at > self._clock() + timedelta(seconds=policy.max_expiry_seconds):
                raise ValueError(f"policy {policy.policy_id} expiry exceeds maximum")
        payload_hash, verified = self._signed_decision(
            req,
            operator_id=by,
            granted=True,
            signature=signature,
            signing_key=signing_key,
            require_signature=policy.require_signature,
        )
        decision = ApprovalDecision(
            decision_id=_short_id(),
            request_id=req.request_id,
            content_hash=req.content_hash,
            action=req.action,
            granted=True,
            approver=by,
            operator_id=by if hardened else "",
            signature=signature or (signing_proof(req, by, signing_key) if signing_key else ""),
            signature_payload_hash=payload_hash,
            signature_verified=verified,
            legacy_approver=not hardened,
            policy_id=policy.policy_id if hardened else "",
            scope=chosen_scope,
            reason=reason,
            expires_at=expires_at if expires_at is not None else req.expires_at,
        )
        self.ledger.append(decision)
        return decision

    def deny(
        self,
        request_id: str,
        *,
        by: str,
        reason: str = "",
        signature: str = "",
        signing_key: str | None = None,
    ) -> ApprovalDecision:
        req = self.ledger.request(request_id)
        if req is None:
            raise KeyError(f"no approval request {request_id!r} on record.")
        policy = self.policy_for(req.action)
        hardened = bool(self.operators or self.policies)
        self._validate_operator(by, policy)
        payload_hash, verified = self._signed_decision(
            req,
            operator_id=by,
            granted=False,
            signature=signature,
            signing_key=signing_key,
            require_signature=policy.require_signature,
        )
        decision = ApprovalDecision(
            decision_id=_short_id(),
            request_id=req.request_id,
            content_hash=req.content_hash,
            action=req.action,
            granted=False,
            approver=by,
            operator_id=by if hardened else "",
            signature=signature
            or (signing_proof(req, by, signing_key, granted=False) if signing_key else ""),
            signature_payload_hash=payload_hash,
            signature_verified=verified,
            legacy_approver=not hardened,
            policy_id=policy.policy_id if hardened else "",
            scope=req.scope,
            reason=reason,
        )
        self.ledger.append(decision)
        return decision

    def revoke(self, decision_id: str, *, by: str, reason: str = "") -> ApprovalRevocation:
        rv = ApprovalRevocation(
            revocation_id=_short_id(), decision_id=decision_id, by=by, reason=reason
        )
        self.ledger.append(rv)
        return rv

    # --- inspection ---------------------------------------------------------
    def status_of(self, request_id: str) -> str:
        req = self.ledger.request(request_id)
        if req is None:
            return "unknown"
        decisions = [d for d in self.ledger.decisions() if d.request_id == request_id]
        if not decisions:
            return "pending"
        if any(not d.granted for d in decisions):
            return "denied"
        policy = self.policy_for(req.action)
        valid = self._valid_decisions(req.action, req.content_hash)
        if any(self._is_revoked(d.decision_id) for d in decisions):
            return "revoked"
        if decisions and all(
            d.expires_at is not None and d.expires_at <= self._clock() for d in decisions
        ):
            return "expired"
        if len({d.operator_id or d.approver for d in valid}) >= policy.required_reviewers:
            return "granted"
        return "pending"

    def pending_requests(self) -> list[ApprovalRequest]:
        return [r for r in self.ledger.requests() if self.status_of(r.request_id) == "pending"]

    def governance_packet(self, request_id: str) -> dict:
        req = self.ledger.request(request_id)
        if req is None:
            raise KeyError(f"no approval request {request_id!r} on record.")
        policy = self.policy_for(req.action)
        decisions = [d for d in self.ledger.decisions() if d.request_id == request_id]
        decision_ids = {d.decision_id for d in decisions}
        revocations = [r for r in self.ledger.revocations() if r.decision_id in decision_ids]
        return {
            "request": req.model_dump(mode="json"),
            "exact_payload": {
                "action": req.action.value,
                "target": req.target,
                "payload": req.payload,
                "content_hash": req.content_hash,
            },
            "risk_classification": req.risk or policy.risk,
            "evaluator_safety_evidence": req.evidence,
            "approval_history": [d.model_dump(mode="json") for d in decisions],
            "revocation_history": [r.model_dump(mode="json") for r in revocations],
            "rollback_plan": req.rollback_plan,
            "policy": policy.model_dump(mode="json"),
            "status": self.status_of(request_id),
        }

    def verify(self) -> GovernanceVerification:
        errors: list[str] = []
        warnings: list[str] = []
        requests = {r.request_id: r for r in self.ledger.requests()}
        for decision in self.ledger.decisions():
            req = requests.get(decision.request_id)
            if req is None:
                errors.append(f"decision {decision.decision_id} references missing request")
                continue
            if decision.content_hash != req.content_hash:
                errors.append(f"decision {decision.decision_id} content hash mismatch")
            if not decision.operator_id:
                warnings.append(
                    f"decision {decision.decision_id} uses legacy approver {decision.approver!r}"
                )
                continue
            policy = self.policy_for(req.action)
            try:
                self._validate_operator(decision.operator_id, policy)
            except ValueError as exc:
                errors.append(f"decision {decision.decision_id} invalid operator: {exc}")
            expected_hash = approval_payload_hash(req, decision.operator_id, decision.granted)
            if decision.signature_payload_hash != expected_hash:
                errors.append(f"decision {decision.decision_id} signature payload hash mismatch")
            if policy.require_signature and not decision.signature_verified:
                errors.append(f"decision {decision.decision_id} signature is not verified")
        return GovernanceVerification(ok=not errors, errors=errors, warnings=warnings)


__all__ = [
    "DEFAULT_APPROVALS_PATH",
    "DEFAULT_OPERATORS_PATH",
    "GovernanceRecord",
    "GovernanceVerification",
    "governed_action_hash",
    "canonical_approval_payload",
    "approval_payload_hash",
    "signing_proof",
    "GovernanceDenied",
    "ApprovalLedger",
    "OperatorLedger",
    "GovernanceGate",
]
