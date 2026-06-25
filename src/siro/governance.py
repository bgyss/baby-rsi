"""Governance gate and human-approval workflow (Goal 10 — Tier 2 foundation).

Tier 2 is "governed scale-up; every step beyond Tier 1 requires an explicit human-approved
governance gate" (``docs/00_principles.md``, ``docs/07_model_providers_and_tiers.md``). This
module makes the human-approval step a **first-class, auditable artifact** rather than an
honor system: the bounds of ``docs/13_self_improvement_loop.md`` — the changes a loop may
*propose* but never *apply* on its own — become enforced through a default-deny gate.

The load-bearing properties are structural, not trust:

- **Default-deny.** :meth:`GovernanceGate.require` proceeds only if a matching, human-issued
  :class:`~siro.schemas.ApprovalDecision` is already on record. Absent one, it records a
  pending :class:`~siro.schemas.ApprovalRequest` (an escalation) and raises
  :class:`GovernanceDenied`. It never authorizes on its own.
- **Hash-binding.** An approval authorizes the *exact* proposed change — a content hash over
  ``(action, target, payload)``. A different change has a different hash and needs its own
  approval; an approval can never be reused for something it didn't approve.
- **No self-approval.** Issuing a decision requires a human ``approver`` and is only reachable
  from the human-operated CLI (``approve`` / ``deny`` / ``revoke``). No agent tool exists that
  grants approval, so an agent can request but never approve.
- **Expiry + revocation.** A granted decision stops authorizing once it expires or is revoked;
  a single-use (``ONCE``) decision is consumed (revoked) the first time it authorizes.

Lowering the tier removes the *capability* (Goals 11/12 only offer governed actions at Tier
2); with no approvals on record everything default-denies, so a lower tier is always safe.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .schemas import (
    ApprovalDecision,
    ApprovalRequest,
    ApprovalRevocation,
    ApprovalScope,
    GovernedAction,
    _utcnow,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .config import SiroConfig

DEFAULT_APPROVALS_PATH = Path("runs/approvals.jsonl")

#: One ledger record is exactly one of these three append-only types.
GovernanceRecord = ApprovalRequest | ApprovalDecision | ApprovalRevocation


def _short_id() -> str:
    return uuid.uuid4().hex[:12]


def governed_action_hash(action: GovernedAction, target: str, payload: dict | None) -> str:
    """A stable content hash over the *exact* proposed change (action + target + payload).

    Canonical JSON (sorted keys) so the same change always hashes the same and a different
    change always differs — this is what binds an approval to one specific action.
    """
    canonical = json.dumps(
        {"action": action.value, "target": target, "payload": payload or {}},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class GovernanceDenied(RuntimeError):
    """Raised when a governed action is attempted without a matching approval (default-deny).

    Carries the pending :class:`~siro.schemas.ApprovalRequest` that was recorded, so the
    caller can surface a precise escalation: "this needs approval of request <id>".
    """

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
    """Append-only ``runs/approvals.jsonl`` of every request, decision, and revocation.

    Heterogeneous records are discriminated by their ``record`` tag, so the full approval
    history — including denied and revoked decisions — stays auditable and replayable.
    """

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
        for r in self.requests():
            if r.request_id == request_id:
                return r
        return None


class GovernanceGate:
    """Default-deny gate: a governed action proceeds only with a matching human approval."""

    def __init__(
        self,
        ledger: ApprovalLedger | None = None,
        *,
        enabled: bool = True,
        clock=_utcnow,
    ) -> None:
        self.ledger = ApprovalLedger() if ledger is None else ledger
        # `enabled` reflects the Tier 2 posture (informational for callers — Goals 11/12 only
        # offer a governed capability when it is true). The gate still default-denies either
        # way, so a disabled gate is never *less* safe.
        self.enabled = enabled
        self._clock = clock

    @classmethod
    def from_config(
        cls, config: "SiroConfig", *, ledger: ApprovalLedger | None = None
    ) -> "GovernanceGate":
        """Build the gate from a tier config's ``governance`` block.

        Governance is on only at Tier ≥ 2 with ``governance.enabled`` (default true at that
        tier). At Tier ≤ 1 the gate is disabled — the governed capabilities aren't offered —
        and lowering the tier therefore needs no code change.
        """
        block = (config.raw.get("governance") or {}) if getattr(config, "raw", None) else {}
        path = block.get("approvals_path", DEFAULT_APPROVALS_PATH)
        enabled = config.tier >= 2 and bool(block.get("enabled", True))
        return cls(ledger=ledger or ApprovalLedger(path), enabled=enabled)

    # --- raising / recording requests --------------------------------------
    def request(
        self,
        action: GovernedAction,
        target: str = "",
        *,
        actor: str = "",
        rationale: str = "",
        payload: dict | None = None,
        scope: ApprovalScope = ApprovalScope.ONCE,
        expires_at: datetime | None = None,
    ) -> ApprovalRequest:
        """Record a pending approval request (an escalation) and return it."""
        req = ApprovalRequest(
            request_id=_short_id(),
            action=action,
            target=target,
            content_hash=governed_action_hash(action, target, payload),
            actor=actor,
            rationale=rationale,
            scope=scope,
            expires_at=expires_at,
        )
        self.ledger.append(req)
        return req

    # --- authorization ------------------------------------------------------
    def _is_revoked(self, decision_id: str) -> bool:
        return any(rv.decision_id == decision_id for rv in self.ledger.revocations())

    def _matching_decision(
        self, action: GovernedAction, content_hash: str
    ) -> ApprovalDecision | None:
        """The newest granted, unexpired, unrevoked decision bound to this exact change."""
        now = self._clock()
        candidates = [
            d
            for d in self.ledger.decisions()
            if d.granted
            and d.action is action
            and d.content_hash == content_hash
            and (d.expires_at is None or d.expires_at > now)
            and not self._is_revoked(d.decision_id)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda d: d.created_at)

    def authorize(
        self,
        action: GovernedAction,
        target: str = "",
        *,
        payload: dict | None = None,
        consume: bool = False,
    ) -> ApprovalDecision | None:
        """Return the matching granted decision for this exact change, or ``None`` (deny).

        A pure check by default. With ``consume=True`` a single-use (``ONCE``) decision is
        revoked as it is returned, so it cannot authorize the same action twice.
        """
        content_hash = governed_action_hash(action, target, payload)
        decision = self._matching_decision(action, content_hash)
        if decision is not None and consume and decision.scope is ApprovalScope.ONCE:
            self.revoke(decision.decision_id, by="governance-gate", reason="consumed (single-use)")
        return decision

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
        """Authorize a governed action or **halt and escalate** (default-deny).

        Returns the matching approval if one is on record (consuming it if single-use);
        otherwise records a pending :class:`~siro.schemas.ApprovalRequest` and raises
        :class:`GovernanceDenied`. This is the entry point a caller (Goals 11/12) wraps a
        governed action in — the action runs only on the returned decision.
        """
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

    # --- human decisions (CLI-only; never an agent tool) -------------------
    def approve(
        self,
        request_id: str,
        *,
        by: str,
        scope: ApprovalScope | None = None,
        expires_at: datetime | None = None,
        reason: str = "",
    ) -> ApprovalDecision:
        """Grant a pending request (a human action). ``by`` is the human approver id."""
        if not by:
            raise ValueError("an approval requires a human approver id (`by`); agents cannot approve.")
        req = self.ledger.request(request_id)
        if req is None:
            raise KeyError(f"no approval request {request_id!r} on record.")
        decision = ApprovalDecision(
            decision_id=_short_id(),
            request_id=req.request_id,
            content_hash=req.content_hash,
            action=req.action,
            granted=True,
            approver=by,
            scope=scope or req.scope,
            reason=reason,
            expires_at=expires_at if expires_at is not None else req.expires_at,
        )
        self.ledger.append(decision)
        return decision

    def deny(self, request_id: str, *, by: str, reason: str = "") -> ApprovalDecision:
        """Deny a pending request (a human action), recorded for audit."""
        if not by:
            raise ValueError("a denial requires a human id (`by`).")
        req = self.ledger.request(request_id)
        if req is None:
            raise KeyError(f"no approval request {request_id!r} on record.")
        decision = ApprovalDecision(
            decision_id=_short_id(),
            request_id=req.request_id,
            content_hash=req.content_hash,
            action=req.action,
            granted=False,
            approver=by,
            scope=req.scope,
            reason=reason,
        )
        self.ledger.append(decision)
        return decision

    def revoke(self, decision_id: str, *, by: str, reason: str = "") -> ApprovalRevocation:
        """Revoke a granted decision (or consume a single-use one), recorded for audit."""
        rv = ApprovalRevocation(
            revocation_id=_short_id(), decision_id=decision_id, by=by, reason=reason
        )
        self.ledger.append(rv)
        return rv

    # --- inspection ---------------------------------------------------------
    def status_of(self, request_id: str) -> str:
        """Resolved status of a request: pending / granted / denied / expired / revoked."""
        req = self.ledger.request(request_id)
        if req is None:
            return "unknown"
        decisions = [d for d in self.ledger.decisions() if d.request_id == request_id]
        if not decisions:
            return "pending"
        latest = max(decisions, key=lambda d: d.created_at)
        if not latest.granted:
            return "denied"
        if self._is_revoked(latest.decision_id):
            return "revoked"
        if latest.expires_at is not None and latest.expires_at <= self._clock():
            return "expired"
        return "granted"

    def pending_requests(self) -> list[ApprovalRequest]:
        """Requests with no decision yet — the human's queue."""
        return [r for r in self.ledger.requests() if self.status_of(r.request_id) == "pending"]


__all__ = [
    "DEFAULT_APPROVALS_PATH",
    "GovernanceRecord",
    "governed_action_hash",
    "GovernanceDenied",
    "ApprovalLedger",
    "GovernanceGate",
]
