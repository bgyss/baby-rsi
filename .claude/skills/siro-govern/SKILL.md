---
name: siro-govern
description: Walk the siro human-approval (governance) workflow. Use when the user wants to request, review, approve, deny, or revoke a governed action (budget increase, tier raise, model train/deploy, egress/evaluator change), manage operators, or verify/export the approval ledger. Enforces the bound that agents request but only humans approve.
---

# Govern siro (human-approval workflow)

Governed actions are the bounds of the system: budget/tier/evaluator/egress/permission
changes and model train/deploy. They proceed only with a recorded, human-issued approval
**bound to the exact change by content hash**. Requests and decisions live in
`runs/approvals.jsonl`.

**The bound you must hold:** you may help *prepare and explain* requests, but `approve` /
`deny` / `revoke` are human decisions. Run them only when the user explicitly tells you to,
and only with a real human `--by` id they supply. Never invent an approver or self-approve.

## Review what's pending

```zsh
uv run siro list-approvals                       # everything
uv run siro list-approvals --status pending      # awaiting a human decision
```

For each pending request, explain to the user: the action kind, target, rationale,
evidence, risk, and rollback plan, so they can make an informed decision. Export a full
audit packet if they want detail:

```zsh
uv run siro export-governance-packet <request_id> --config config/tier2.governed.yaml
```

## Record a request (agents/operators may do this)

```zsh
uv run siro request-approval <action> --target <what> \
    --payload '<json describing the exact change>' \
    --rationale "<why>" --evidence "<link>" --rollback-plan "<plan>"
```

The `--payload` JSON binds the approval to the exact change — keep it precise. `<action>`
is one of the governed-action kinds (see `uv run siro request-approval --help`).

## Make a decision (human-only — only on explicit instruction)

```zsh
uv run siro approve <request_id> --by <human>
uv run siro deny    <request_id> --by <human> --reason "<why>"
uv run siro revoke  <decision_id> --by <human> --reason "<why>"
```

### Identity-signed approvals (Tier 2, Goal 19)

For signed, identity-validated proofs, operators are registered first and the approval
carries an HMAC proof over the canonical payload:

```zsh
uv run siro create-operator alice --display-name "Alice Reviewer" --role approver
uv run siro list-operators
uv run siro approve <request_id> --by alice --signing-key "$LOCAL_DEV_SIGNING_KEY" \
    --config config/tier2.governed.yaml
```

The signing key is provided by the human at decision time and never stored. Some actions
require two-person approval and requester≠approver separation — `verify-governance` will
flag a violation.

## Verify the ledger

```zsh
uv run siro verify-governance --config config/tier2.governed.yaml   # identities, hashes, signatures
```

Run this after any batch of decisions, and whenever **/siro-watch** shows governance
activity, to confirm every approval validates (active operator, role, signature, expiry,
exact content hash). Report any failure verbatim — a broken proof is a security finding,
not a warning to smooth over.
