# Goal Prompt 16 - Durable Research Store and Query Layer

## Goal

Add a durable queryable storage layer while preserving JSONL as the human-readable audit
format. This goal addresses the persistence refinement in `../14_project_retrospective.md`:
JSONL is right for the MVP, but production pilots need concurrency, migrations, querying,
idempotency, and tamper-evidence.

Depends on Goals 01, 03, 05, 09, 10, 12.

## Requirements

- Define a storage interface for attempts, research attempts, model calls, memory entries,
  meta-changes, governance records, checkpoints, and model artifacts.
- Implement a SQLite backend for local multi-run development:
  - schema migrations,
  - append-only event tables,
  - query helpers for summaries,
  - idempotency keys for repeated writes,
  - export back to JSONL.
- Keep existing JSONL archives as the default simple backend until the SQLite backend is
  enabled by config.
- Add stable IDs where missing:
  - run ID,
  - cycle ID,
  - attempt ID,
  - model-call ID,
  - lineage ID,
  - approval/request/decision ID.
- Add tamper-evident optional hash chaining for governance and artifact records.
- Update summaries to read through the storage interface rather than assuming raw JSONL.
- Add docs for migration, export, and backup.

## Acceptance criteria

- Existing JSONL-backed commands still work unchanged.
- With SQLite enabled, repeated writes with the same idempotency key do not duplicate
  records.
- `summarize-runs` and `summarize-research` work against both JSONL and SQLite stores.
- A SQLite store can export JSONL files compatible with existing readers.
- Governance records can be hash-chained and verified.
- Tests cover migrations from an empty database and at least one previous schema version.

## Constraints

- Do not remove JSONL support; it remains the transparent audit/export format.
- Do not make production storage a hidden dependency for Tier 0 local tests.
- Do not store provider API keys, credentials, or full secret datasets in the research
  store.
- Do not let agents modify storage migrations or tamper-evidence policy without human
  review.

## Self-improvement

This goal improves the "observe", "reflect", and "record" stages of
`../13_self_improvement_loop.md` by making research memory more reliable and queryable.

- **Records**: every event currently stored in JSONL, plus stable lineage and idempotency
  metadata.
- **Reflects / proposes**: summaries and meta-research can query richer historical context
  without treating retrieved memory as instructions.
- **Validated / gated**: storage migrations and summary changes must preserve existing JSONL
  compatibility and pass round-trip tests.
- **Bounds**: changing audit retention, ledger integrity, or tamper-evidence behavior is
  human-gated.
