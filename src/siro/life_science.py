"""Two-stage drug/life-science workflow: screening gates confirmation (Goal 27).

The drug/life-science pack is the capstone that combines both new regimes on one workflow
(``docs/18_generalizing_to_sciences.md``):

- **Screening (Regime B, offline).** Cheap, pinned-surrogate scoring ranks candidate
  molecules/sequences with no real-world action. It runs the inner self-improvement loop under
  the Goal 24 statistical gate (``packs/life_science/tasks/screening``).
- **Confirmation (Regime C, governed).** A small number of high-ranked candidates are proposed
  as Goal 26 external experiments (a wet-lab assay). Promotion to *confirmed* requires an
  ingested, signed assay result bound to a human approval; the execution plane runs no part of
  it (``packs/life_science/tasks/confirmation``).

This module supplies the **load-bearing bound between the two stages**: a costly, irreversible
wet-lab confirmation may only be *proposed* for a candidate that has cleared the in-silico
screen (the Goal 11 promotion-before-budget pattern), so expensive confirmations stay few and
high-value. The screening evaluator and its fixtures live in the pack; the confirmation
mechanism is the existing :mod:`siro.external` boundary — this module only enforces that the
screen gates the proposal. No function here approves, attests, or runs a wet-lab step.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .external import external_spec_for, propose_external_experiment
from .schemas import ApprovalRequest, StatisticalEvidence

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .governance import GovernanceGate
    from .research import ResearchTask


class ConfirmationNotEarned(RuntimeError):
    """Raised when a wet-lab confirmation is proposed for an un-screened candidate.

    Screening gates confirmation: a candidate must first clear the offline in-silico screen
    (a promoting Goal 24 statistical assessment) before its costly, irreversible confirmation
    may even be *proposed* for human approval. This is a hard precondition, not advice.
    """


def screen_clears(evidence: StatisticalEvidence | None) -> bool:
    """Whether a screening assessment cleared the in-silico screen.

    ``evidence`` is the :class:`~siro.schemas.StatisticalEvidence` from
    :func:`siro.research.assess_statistical` on a *screening* task. The screen clears only when
    the candidate is reproducible across the policy's fixed seeded replicates **and** its
    oriented primary-metric gain clears the confidence bound — exactly the Goal 24 promotion
    rule. A within-noise or non-reproducible screen does not clear and cannot gate a costly
    confirmation.
    """
    return evidence is not None and evidence.reproducible and evidence.promoted


def screen_summary(evidence: StatisticalEvidence | None) -> str:
    """A short, auditable description of the screen result for the approval evidence trail."""
    if evidence is None:
        return "no in-silico screen on record"
    interval = f"[{evidence.primary_delta_low:g}, {evidence.primary_delta_high:g}]"
    return (
        f"in-silico screen: {evidence.primary_name} delta CI {interval} across "
        f"{evidence.replicates} seeds at {int(evidence.confidence * 100)}% confidence "
        f"(reproducible={evidence.reproducible}, promoted={evidence.promoted})"
    )


def propose_confirmation(
    gate: "GovernanceGate",
    confirmation_task: "ResearchTask",
    candidate_code: str,
    *,
    screen_evidence: StatisticalEvidence | None,
    actor: str = "",
    rationale: str = "",
    rollback_plan: str = "",
    evidence: list[str] | None = None,
) -> ApprovalRequest:
    """Propose a governed wet-lab confirmation **only** for a screened candidate (Goal 27).

    Enforces the screening-before-confirmation bound: if ``screen_evidence`` did not clear the
    in-silico screen (:func:`screen_clears`), no proposal is emitted and
    :class:`ConfirmationNotEarned` is raised — a candidate cannot skip the cheap offline screen
    to reach a costly, irreversible assay. When the screen cleared, the candidate's external
    experiment is recorded as a default-deny Goal 26 :class:`~siro.schemas.ExternalExperimentSpec`
    approval request (still human-approved, never agent-authorized), with the screen result
    attached to the evidence trail so a reviewer sees *why* this candidate earned the assay.
    """
    if not screen_clears(screen_evidence):
        raise ConfirmationNotEarned(
            "candidate has not cleared the in-silico screen; a costly, irreversible wet-lab "
            "confirmation may only be proposed for a screened candidate "
            "(screening-before-confirmation, Goal 27)"
        )
    spec = external_spec_for(confirmation_task, candidate_code)
    trail = [screen_summary(screen_evidence), *(evidence or [])]
    return propose_external_experiment(
        gate,
        spec,
        actor=actor,
        rationale=rationale,
        rollback_plan=rollback_plan,
        evidence=trail,
    )


__all__ = [
    "ConfirmationNotEarned",
    "screen_clears",
    "screen_summary",
    "propose_confirmation",
]
