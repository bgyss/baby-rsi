"""Durable, queryable storage layer (Goal 16).

JSONL is the right MVP archive — human-readable, diff-able, append-only — but a production
pilot needs concurrency, migrations, idempotent writes, querying, and tamper-evidence
(``docs/14_project_retrospective.md``). This module adds a **storage interface** over every
append-only record stream the system keeps, with two backends:

- :class:`JSONLStore` — the **default**. A uniform reader/writer over the existing
  ``runs/*.jsonl`` files, so nothing about the Tier 0 local flow changes and JSONL stays the
  transparent audit/export format.
- :class:`SQLiteStore` — opt-in via config. One SQLite database with schema migrations, an
  append-only ``events`` table, idempotency keys (a repeated write with the same key is a
  no-op), per-stream hash chaining for tamper-evidence, and JSONL export/import that
  round-trips byte-for-byte with the existing readers.

The schema in :mod:`siro.schemas` remains the contract; this is only *where* records land.
Bounds (``CLAUDE.md``): the store never holds credentials or secret datasets — it persists the
same typed records the JSONL archives already do — and migrations / tamper-evidence policy are
human-gated config, never agent-editable.

Scope note: this is the durable home for the **append-only event** streams. Compute
*checkpoints* (:class:`~siro.scale.CheckpointStore`) stay in their dedicated per-experiment
files because they are mutable, latest-wins resumable state rather than an immutable event log;
the trained-model **weight blobs** likewise stay in :class:`~siro.model_training.ArtifactStore`
while their lineage metadata (the ``artifacts`` stream) lands here.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .archive import DEFAULT_ATTEMPTS_PATH, DEFAULT_MODEL_CALLS_PATH
from .governance import DEFAULT_APPROVALS_PATH
from .memory import DEFAULT_MEMORY_PATH
from .meta import DEFAULT_META_CHANGES_PATH
from .model_training import DEFAULT_MODEL_ARTIFACTS_PATH, DEFAULT_MODEL_REGISTRY_PATH
from .research import DEFAULT_RESEARCH_ATTEMPTS_PATH
from .schemas import (
    ApprovalDecision,
    ApprovalRequest,
    ApprovalRevocation,
    Attempt,
    MemoryEntry,
    MetaChangeRecord,
    ModelCall,
    ModelDeployment,
    ResearchAttempt,
    TrainedModelArtifact,
    TrainingAttempt,
)
from .training import DEFAULT_TRAINING_ATTEMPTS_PATH

DEFAULT_STORE_PATH = Path("runs/siro.db")

#: The current SQLite schema version (see ``_MIGRATIONS``).
SCHEMA_VERSION = 2


def _parse_governance(line: str) -> BaseModel:
    """Parse a heterogeneous governance record by its discriminating ``record`` tag."""
    tag = json.loads(line).get("record")
    if tag == "decision":
        return ApprovalDecision.model_validate_json(line)
    if tag == "revocation":
        return ApprovalRevocation.model_validate_json(line)
    return ApprovalRequest.model_validate_json(line)


@dataclass(frozen=True)
class StreamSpec:
    """One append-only record stream: its model, natural id field(s), and JSONL home."""

    name: str
    default_path: Path
    id_fields: tuple[str, ...]
    parse: Callable[[str], BaseModel]
    hash_chained: bool = False


#: Every append-only stream the system persists. Governance + model artifacts default to
#: hash-chained (tamper-evident) — the records whose integrity matters most.
STREAMS: dict[str, StreamSpec] = {
    spec.name: spec
    for spec in (
        StreamSpec("attempts", DEFAULT_ATTEMPTS_PATH, ("attempt_id",), Attempt.model_validate_json),
        StreamSpec(
            "research_attempts", DEFAULT_RESEARCH_ATTEMPTS_PATH, ("attempt_id",),
            ResearchAttempt.model_validate_json,
        ),
        StreamSpec(
            "training_attempts", DEFAULT_TRAINING_ATTEMPTS_PATH, ("attempt_id",),
            TrainingAttempt.model_validate_json,
        ),
        StreamSpec("model_calls", DEFAULT_MODEL_CALLS_PATH, ("call_id",), ModelCall.model_validate_json),
        StreamSpec("memory", DEFAULT_MEMORY_PATH, ("entry_id",), MemoryEntry.model_validate_json),
        StreamSpec(
            "meta_changes", DEFAULT_META_CHANGES_PATH, ("record_id",),
            MetaChangeRecord.model_validate_json,
        ),
        StreamSpec(
            "governance", DEFAULT_APPROVALS_PATH,
            ("request_id", "decision_id", "revocation_id"), _parse_governance, hash_chained=True,
        ),
        StreamSpec(
            "artifacts", DEFAULT_MODEL_ARTIFACTS_PATH, ("artifact_id",),
            TrainedModelArtifact.model_validate_json, hash_chained=True,
        ),
        StreamSpec(
            "deployments", DEFAULT_MODEL_REGISTRY_PATH, ("deployment_id",),
            ModelDeployment.model_validate_json,
        ),
    )
}


def _record_id(spec: StreamSpec, payload: dict[str, Any]) -> str:
    """The natural id of a record (the first of the stream's id fields that is present)."""
    for field in spec.id_fields:
        value = payload.get(field)
        if value:
            return str(value)
    # No natural id (should not happen for our schemas): fall back to a content hash.
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def _chain_hash(prev_hash: str, payload_json: str) -> str:
    return hashlib.sha256((prev_hash + payload_json).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ChainVerification:
    """Result of verifying a stream's tamper-evident hash chain."""

    stream: str
    ok: bool
    checked: int
    supported: bool = True
    broken_seq: int | None = None
    detail: str = ""


def _read_jsonl(path: Path) -> list[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        return [line for line in (raw.strip() for raw in fh) if line]


class Store:
    """Abstract storage interface over the append-only record streams."""

    backend: str = "base"

    def append(self, stream: str, record: BaseModel, *, idempotency_key: str | None = None) -> bool:
        """Append ``record`` to ``stream``; return True if written, False if deduped."""
        raise NotImplementedError

    def read(self, stream: str) -> list[BaseModel]:
        """Every record in ``stream``, oldest first (typed)."""
        raise NotImplementedError

    def export_jsonl(self, stream: str, path: str | Path) -> int:
        """Write ``stream`` to a JSONL file compatible with the existing readers."""
        raise NotImplementedError

    def import_jsonl(self, stream: str, path: str | Path) -> int:
        """Append every record from a JSONL file into ``stream`` (idempotent); return inserts."""
        records = [STREAMS[stream].parse(line) for line in _read_jsonl(Path(path))]
        return sum(1 for rec in records if self.append(stream, rec))

    def verify_chain(self, stream: str) -> ChainVerification:
        """Verify the tamper-evident hash chain for ``stream``."""
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - trivial
        pass


class JSONLStore(Store):
    """Uniform access to the existing ``runs/*.jsonl`` files (the default, transparent backend).

    ``append`` writes a line in the exact format the per-module archives use, so this backend
    and the existing :class:`~siro.archive.JSONLArchive` family stay byte-compatible. JSONL has
    no hash chain, so :meth:`verify_chain` reports ``supported=False``.
    """

    backend = "jsonl"

    def __init__(self, base_dir: str | Path | None = None) -> None:
        # When ``base_dir`` is given, every stream lives under it as ``<stream>.jsonl``;
        # otherwise each stream uses its canonical ``runs/*.jsonl`` path.
        self.base_dir = Path(base_dir) if base_dir is not None else None

    def path_for(self, stream: str) -> Path:
        spec = STREAMS[stream]
        if self.base_dir is not None:
            return self.base_dir / f"{stream}.jsonl"
        return spec.default_path

    def append(self, stream: str, record: BaseModel, *, idempotency_key: str | None = None) -> bool:
        path = self.path_for(stream)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(record.model_dump_json() + "\n")
        return True

    def read(self, stream: str) -> list[BaseModel]:
        spec = STREAMS[stream]
        return [spec.parse(line) for line in _read_jsonl(self.path_for(stream))]

    def export_jsonl(self, stream: str, path: str | Path) -> int:
        lines = _read_jsonl(self.path_for(stream))
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
        return len(lines)

    def verify_chain(self, stream: str) -> ChainVerification:
        return ChainVerification(
            stream=stream, ok=True, checked=0, supported=False,
            detail="JSONL backend has no hash chain; enable the SQLite backend for tamper-evidence.",
        )


# --- SQLite backend ---------------------------------------------------------

_MIGRATIONS: list[tuple[int, tuple[str, ...]]] = [
    (
        1,
        (
            """
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                stream TEXT NOT NULL,
                record_id TEXT,
                idempotency_key TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT,
                UNIQUE(stream, idempotency_key)
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_events_stream ON events(stream, seq)",
        ),
    ),
    # v2 adds the tamper-evident hash-chain columns (a real prior-version migration).
    (
        2,
        (
            "ALTER TABLE events ADD COLUMN prev_hash TEXT",
            "ALTER TABLE events ADD COLUMN hash TEXT",
        ),
    ),
]


class SQLiteStore(Store):
    """Append-only event store on SQLite: migrations, idempotency, and hash chaining.

    All streams share one ``events`` table keyed by ``(stream, idempotency_key)`` — a repeated
    write with the same key is silently ignored (idempotent ingestion). Hash-chained streams
    additionally link each row to the previous one, so any later edit to the database is
    detectable via :meth:`verify_chain`.
    """

    backend = "sqlite"

    def __init__(self, path: str | Path = DEFAULT_STORE_PATH, *, migrate: bool = True) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        if migrate:
            self.migrate()

    # ----- migrations ------------------------------------------------------
    def schema_version(self) -> int:
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version INTEGER PRIMARY KEY, applied_at TEXT)"
        )
        row = self.conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def migrate(self, target: int | None = None) -> int:
        """Apply pending migrations up to ``target`` (default: latest). Returns the new version."""
        from datetime import datetime, timezone

        target = SCHEMA_VERSION if target is None else target
        current = self.schema_version()
        for version, statements in _MIGRATIONS:
            if current < version <= target:
                for sql in statements:
                    self.conn.execute(sql)
                self.conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (version, datetime.now(timezone.utc).isoformat()),
                )
                current = version
        self.conn.commit()
        return current

    # ----- writes ----------------------------------------------------------
    def _last_hash(self, stream: str) -> str:
        row = self.conn.execute(
            "SELECT hash FROM events WHERE stream=? ORDER BY seq DESC LIMIT 1", (stream,)
        ).fetchone()
        return row[0] if row and row[0] else ""

    def append(self, stream: str, record: BaseModel, *, idempotency_key: str | None = None) -> bool:
        if stream not in STREAMS:
            raise KeyError(f"unknown stream {stream!r}; known: {sorted(STREAMS)}")
        spec = STREAMS[stream]
        payload = record.model_dump_json()
        data = json.loads(payload)
        record_id = _record_id(spec, data)
        key = idempotency_key or record_id
        created_at = str(data.get("created_at") or "")
        prev_hash = self._last_hash(stream) if spec.hash_chained else ""
        row_hash = _chain_hash(prev_hash, payload) if spec.hash_chained else None
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO events"
            "(stream, record_id, idempotency_key, payload, created_at, prev_hash, hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (stream, record_id, key, payload, created_at, prev_hash or None, row_hash),
        )
        self.conn.commit()
        return cur.rowcount > 0

    # ----- reads -----------------------------------------------------------
    def _payloads(self, stream: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT payload FROM events WHERE stream=? ORDER BY seq", (stream,)
        ).fetchall()
        return [row[0] for row in rows]

    def read(self, stream: str) -> list[BaseModel]:
        spec = STREAMS[stream]
        return [spec.parse(payload) for payload in self._payloads(stream)]

    def export_jsonl(self, stream: str, path: str | Path) -> int:
        payloads = self._payloads(stream)
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("".join(p + "\n" for p in payloads), encoding="utf-8")
        return len(payloads)

    # ----- tamper-evidence -------------------------------------------------
    def verify_chain(self, stream: str) -> ChainVerification:
        spec = STREAMS[stream]
        if not spec.hash_chained:
            return ChainVerification(
                stream=stream, ok=True, checked=0, supported=False,
                detail=f"stream {stream!r} is not hash-chained",
            )
        rows = self.conn.execute(
            "SELECT seq, payload, prev_hash, hash FROM events WHERE stream=? ORDER BY seq",
            (stream,),
        ).fetchall()
        prev = ""
        for seq, payload, stored_prev, stored_hash in rows:
            expected = _chain_hash(prev, payload)
            if (stored_prev or "") != prev or stored_hash != expected:
                return ChainVerification(
                    stream=stream, ok=False, checked=len(rows), broken_seq=int(seq),
                    detail=f"hash chain broken at seq {seq}",
                )
            prev = stored_hash
        return ChainVerification(stream=stream, ok=True, checked=len(rows))

    def close(self) -> None:
        self.conn.close()


# --- config wiring ----------------------------------------------------------


@dataclass(frozen=True)
class StorageConfig:
    """Parsed ``storage`` config block. Default is the transparent JSONL backend."""

    backend: str = "jsonl"
    path: Path = DEFAULT_STORE_PATH
    base_dir: Path | None = None


def storage_from_config(config: Any) -> StorageConfig:
    """Parse a ``storage`` block from a tier config (or fall back to the JSONL default)."""
    block = (config.raw.get("storage") or {}) if getattr(config, "raw", None) else {}
    return StorageConfig(
        backend=str(block.get("backend", "jsonl")),
        path=Path(block.get("path", DEFAULT_STORE_PATH)),
        base_dir=Path(block["base_dir"]) if block.get("base_dir") else None,
    )


def open_store(config: StorageConfig | Any) -> Store:
    """Open the configured store. Accepts a :class:`StorageConfig` or a ``SiroConfig``."""
    storage = config if isinstance(config, StorageConfig) else storage_from_config(config)
    if storage.backend == "sqlite":
        return SQLiteStore(storage.path)
    if storage.backend == "jsonl":
        return JSONLStore(storage.base_dir)
    raise ValueError(f"unknown storage backend {storage.backend!r} (expected 'jsonl' or 'sqlite')")


__all__ = [
    "DEFAULT_STORE_PATH",
    "SCHEMA_VERSION",
    "STREAMS",
    "StreamSpec",
    "ChainVerification",
    "Store",
    "JSONLStore",
    "SQLiteStore",
    "StorageConfig",
    "storage_from_config",
    "open_store",
]
