---
name: siro-govern
description: Walk the siro human-approval workflow from Codex. Use when the user wants to request, review, approve, deny, or revoke a governed action, manage operators, or verify/export the approval ledger. Enforces the bound that agents request but only humans approve.
---

# Govern siro

Governed actions are the bounds of the system: budget/tier/evaluator/egress/permission
changes and model train/deploy. They proceed only with a recorded, human-issued approval
bound to the exact change by content hash. Requests and decisions live in
`runs/approvals.jsonl`.

The bound you must hold: you may help prepare and explain requests, but `approve`,
`deny`, and `revoke` are human decisions. Run them only when the user explicitly tells you
to, and only with a real human `--by` id they supply. Never invent an approver or
self-approve.

## Review what's pending

```zsh
uv run siro list-approvals
uv run siro list-approvals --status pending
```

For each pending request, explain the action kind, target, rationale, evidence, risk, and
rollback plan so the user can make an informed decision. Export a full audit packet if
they want detail:

```zsh
uv run siro export-governance-packet <request_id> --config config/tier2.governed.yaml
```

## Record a request

```zsh
uv run siro request-approval <action> --target <what> \
    --payload '<json describing the exact change>' \
    --rationale "<why>" --evidence "<link>" --rollback-plan "<plan>"
```

The `--payload` JSON binds the approval to the exact change. Keep it precise. `<action>` is
one of the governed-action kinds; check `uv run siro request-approval --help` if unsure.

## Make a decision

Human-only, only on explicit instruction:

```zsh
uv run siro approve <request_id> --by <human>
uv run siro deny    <request_id> --by <human> --reason "<why>"
uv run siro revoke  <decision_id> --by <human> --reason "<why>"
```

## Identity-signed approvals

For signed, identity-validated proofs, operators are registered first and the approval
carries an HMAC proof over the canonical payload:

```zsh
uv run siro create-operator alice --display-name "Alice Reviewer" --role approver
uv run siro list-operators
uv run siro approve <request_id> --by alice --signing-key "$LOCAL_DEV_SIGNING_KEY" \
    --config config/tier2.governed.yaml
```

The signing key is provided by the human at decision time and never stored. Some actions
require two-person approval and requester/approver separation; `verify-governance` will
flag violations.

## Verify the ledger

```zsh
uv run siro verify-governance --config config/tier2.governed.yaml
```

Run this after any batch of decisions, and whenever `siro-watch` shows governance activity.
Report any failure verbatim: a broken proof is a security finding.
