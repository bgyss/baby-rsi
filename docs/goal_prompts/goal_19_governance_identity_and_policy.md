# Goal Prompt 19 - Governance Identity and Policy Hardening

## Goal

Strengthen Tier 2 governance from a structurally correct local ledger into a production-ready
human approval system. This goal addresses the governance refinement in
`../14_project_retrospective.md`: a free-form `--by` string is enough for the testbed, but
not enough for serious high-risk approvals.

Depends on Goals 10, 11, 12, 16.

## Requirements

- Add typed operator identities:
  - stable operator ID,
  - display name,
  - role (`requester`, `reviewer`, `approver`, `admin`),
  - authentication method metadata,
  - active/revoked status.
- Replace free-form approver strings with validated operator identities for new approval
  records while preserving read compatibility with existing ledgers.
- Add signed approval records:
  - canonical request payload,
  - content hash,
  - signer/operator ID,
  - signature or local signing proof,
  - verification status.
- Add policy templates per governed action:
  - required reviewer count,
  - required approver role,
  - one-person vs two-person approval,
  - maximum scope and expiry,
  - required rationale fields,
  - required evidence attachments or links.
- Add governance packets:
  - request,
  - exact diff/payload,
  - risk classification,
  - evaluator/safety evidence,
  - approval/denial/revocation history,
  - rollback plan.
- Update CLI:
  - create/list/revoke operators,
  - verify approval ledger,
  - export governance packet,
  - approve with identity validation.

## Acceptance criteria

- A new approval cannot be granted by an unknown, inactive, or unauthorized operator.
- High-risk governed actions can require two distinct approvers.
- Approval signatures or signing proofs verify against the canonical request hash.
- Existing Goal 10 ledgers remain readable, with legacy approver strings clearly marked as
  legacy records.
- Revocation and expiry continue to work.
- Governance packet export includes the exact governed action payload, risk evidence, and
  rollback plan.
- No agent tool can create operators, grant approval, sign approval, or change governance
  policy.

## Constraints

- Do not make governance dependent on a specific external identity provider for local
  development. External identity integrations can be adapters later.
- Do not weaken default-deny behavior.
- Do not allow an approval to authorize a different content hash.
- Do not allow the requester and required approver to be the same identity when policy says
  separation is required.
- Do not store private signing keys in the research archive or model prompts.

## Self-improvement

This goal hardens the human gate around the bounded self-improvement cycle in
`../13_self_improvement_loop.md`.

- **Records**: operator identities, policy decisions, signed approvals, revocations, and
  exported governance packets.
- **Reflects / proposes**: loops may propose governed actions, but approval policy is applied
  by the governance gate and reviewed by humans.
- **Validated / gated**: governed actions proceed only when identity, policy, signature,
  expiry, and content-hash checks all pass.
- **Bounds**: changing governance policy, operator roles, approval thresholds, or signing
  requirements is itself a governed action.
