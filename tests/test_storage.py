"""Goal 16 — durable, queryable storage layer.

Exercised offline. JSONL stays the default, transparent format; the SQLite backend adds
migrations, idempotent writes, hash-chained tamper-evidence, and JSONL round-trip — all of
which must preserve compatibility with the existing readers.
"""

from __future__ import annotations

import json

import pytest

from siro.archive import JSONLArchive
from siro.schemas import (
    ApprovalRequest,
    ApprovalScope,
    Attempt,
    AttemptStatus,
    Candidate,
    GovernedAction,
    ModelCall,
)
from siro.storage import (
    SCHEMA_VERSION,
    STREAMS,
    JSONLStore,
    SQLiteStore,
    StorageConfig,
    open_store,
    storage_from_config,
)


def _attempt(i: int, *, status=AttemptStatus.REJECTED, reason="1 test(s) failing") -> Attempt:
    return Attempt(
        attempt_id=f"a{i}",
        task_id="t",
        candidate=Candidate(candidate_id=f"c{i}", task_id="t", code="x = 1"),
        status=status,
        reason=reason,
    )


def _request(i: int) -> ApprovalRequest:
    return ApprovalRequest(
        request_id=f"req{i}",
        action=GovernedAction.BUDGET_INCREASE,
        target="max_usd_per_run",
        payload={"i": i},
        content_hash=f"h{i}",
        scope=ApprovalScope.ONCE,
    )


# --- stable IDs -------------------------------------------------------------


def test_model_call_has_stable_unique_id():
    a, b = ModelCall(provider="p", model="m", prompt_hash="h"), ModelCall(
        provider="p", model="m", prompt_hash="h"
    )
    assert a.call_id and b.call_id and a.call_id != b.call_id


# --- JSONL backend (the default) -------------------------------------------


def test_jsonl_store_roundtrip(tmp_path):
    store = JSONLStore(tmp_path)
    assert store.append("attempts", _attempt(0))
    assert store.append("attempts", _attempt(1))
    got = store.read("attempts")
    assert [a.attempt_id for a in got] == ["a0", "a1"]


def test_jsonl_store_reads_existing_archive_files(tmp_path):
    # JSONLArchive and JSONLStore agree on format/path, so summaries can read through either.
    archive = JSONLArchive(tmp_path / "attempts.jsonl")
    archive.append(_attempt(0))
    store = JSONLStore(tmp_path)
    assert [a.attempt_id for a in store.read("attempts")] == ["a0"]


# --- SQLite migrations ------------------------------------------------------


def test_migrations_from_empty_database(tmp_path):
    store = SQLiteStore(tmp_path / "s.db")
    assert store.schema_version() == SCHEMA_VERSION
    assert store.append("attempts", _attempt(0))
    assert [a.attempt_id for a in store.read("attempts")] == ["a0"]


def test_migration_from_previous_schema_version_preserves_rows(tmp_path):
    store = SQLiteStore(tmp_path / "s.db", migrate=False)
    # Stop at v1: the events table exists without the hash-chain columns.
    assert store.migrate(target=1) == 1
    cols = {row[1] for row in store.conn.execute("PRAGMA table_info(events)").fetchall()}
    assert "hash" not in cols and "prev_hash" not in cols

    # Insert a v1-era row directly (no hash columns), then migrate forward.
    payload = _attempt(0).model_dump_json()
    store.conn.execute(
        "INSERT INTO events(stream, record_id, idempotency_key, payload, created_at) "
        "VALUES ('attempts', 'a0', 'a0', ?, '')",
        (payload,),
    )
    store.conn.commit()

    assert store.migrate() == SCHEMA_VERSION
    cols2 = {row[1] for row in store.conn.execute("PRAGMA table_info(events)").fetchall()}
    assert {"hash", "prev_hash"} <= cols2
    # The v1 row survived the migration and still reads back as a typed record.
    assert [a.attempt_id for a in store.read("attempts")] == ["a0"]


# --- idempotency ------------------------------------------------------------


def test_idempotent_writes_do_not_duplicate(tmp_path):
    store = SQLiteStore(tmp_path / "s.db")
    rec = _attempt(0)
    assert store.append("attempts", rec) is True
    assert store.append("attempts", rec) is False  # same id ⇒ deduped
    assert len(store.read("attempts")) == 1


def test_distinct_idempotency_keys_keep_both(tmp_path):
    store = SQLiteStore(tmp_path / "s.db")
    rec = _attempt(0)
    assert store.append("attempts", rec, idempotency_key="k1")
    assert store.append("attempts", rec, idempotency_key="k2")
    assert len(store.read("attempts")) == 2


# --- export / import round-trip --------------------------------------------


def test_sqlite_export_matches_source_jsonl(tmp_path):
    src = tmp_path / "attempts.jsonl"
    archive = JSONLArchive(src)
    for i in range(3):
        archive.append(_attempt(i))

    store = SQLiteStore(tmp_path / "s.db")
    assert store.import_jsonl("attempts", src) == 3
    out = tmp_path / "export.jsonl"
    assert store.export_jsonl("attempts", out) == 3

    # Byte-for-byte compatible with the existing reader.
    assert sorted(src.read_text().splitlines()) == sorted(out.read_text().splitlines())
    assert [a.attempt_id for a in JSONLArchive(out).read_all()] == ["a0", "a1", "a2"]


def test_reimport_is_idempotent(tmp_path):
    src = tmp_path / "attempts.jsonl"
    archive = JSONLArchive(src)
    for i in range(2):
        archive.append(_attempt(i))
    store = SQLiteStore(tmp_path / "s.db")
    assert store.import_jsonl("attempts", src) == 2
    assert store.import_jsonl("attempts", src) == 0  # nothing new on re-import


# --- tamper-evident hash chaining ------------------------------------------


def test_governance_chain_verifies_and_detects_tampering(tmp_path):
    store = SQLiteStore(tmp_path / "s.db")
    for i in range(3):
        store.append("governance", _request(i))
    good = store.verify_chain("governance")
    assert good.ok and good.supported and good.checked == 3

    # Tamper with a stored payload; the chain must no longer verify.
    store.conn.execute(
        "UPDATE events SET payload=? WHERE stream='governance' AND record_id='req1'",
        (json.dumps({"record": "request", "request_id": "req1"}),),
    )
    store.conn.commit()
    bad = store.verify_chain("governance")
    assert not bad.ok and bad.broken_seq is not None


def test_non_chained_stream_reports_unsupported(tmp_path):
    store = SQLiteStore(tmp_path / "s.db")
    store.append("attempts", _attempt(0))
    result = store.verify_chain("attempts")
    assert result.supported is False and result.ok is True


def test_artifacts_stream_is_hash_chained():
    assert STREAMS["artifacts"].hash_chained and STREAMS["governance"].hash_chained
    assert not STREAMS["attempts"].hash_chained


# --- summaries read through both backends -----------------------------------


def test_both_backends_return_equivalent_records(tmp_path):
    jsonl_dir = tmp_path / "j"
    jsonl = JSONLStore(jsonl_dir)
    sqlite = SQLiteStore(tmp_path / "s.db")
    attempts = [_attempt(i) for i in range(4)]
    for rec in attempts:
        jsonl.append("attempts", rec)
        sqlite.append("attempts", rec)
    assert [a.attempt_id for a in jsonl.read("attempts")] == [
        a.attempt_id for a in sqlite.read("attempts")
    ]


# --- config wiring ----------------------------------------------------------


class _Cfg:
    def __init__(self, raw):
        self.raw = raw


def test_storage_from_config_defaults_to_jsonl():
    assert storage_from_config(_Cfg({})).backend == "jsonl"


def test_open_store_selects_backend(tmp_path):
    jsonl = open_store(StorageConfig(backend="jsonl", base_dir=tmp_path))
    assert jsonl.backend == "jsonl"
    sqlite = open_store(StorageConfig(backend="sqlite", path=tmp_path / "s.db"))
    assert sqlite.backend == "sqlite"
    with pytest.raises(ValueError, match="unknown storage backend"):
        open_store(StorageConfig(backend="redis"))
