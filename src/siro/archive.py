"""JSONL archive — the first, simplest persistence for attempts and the audit ledger.

Append-only JSONL keeps the record auditable and trivially diff-able. SQLite is a
later optimization (``docs/10_repo_structure.md``); the schema in ``schemas`` is the
contract, not the storage format.

Every attempt — promoted *or* rejected — is appended. Nothing is overwritten or
deleted: that is what makes negative results first-class data.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from .schemas import Attempt, ModelCall

DEFAULT_ATTEMPTS_PATH = Path("runs/attempts.jsonl")
DEFAULT_MODEL_CALLS_PATH = Path("runs/model_calls.jsonl")


def _append_line(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(payload + "\n")


def _read_lines(path: Path) -> Iterator[str]:
    if not path.exists():
        return iter(())
    with path.open("r", encoding="utf-8") as fh:
        return iter([line for line in (raw.strip() for raw in fh) if line])


class JSONLArchive:
    """Append-only archive of :class:`Attempt` records."""

    def __init__(self, path: str | Path = DEFAULT_ATTEMPTS_PATH) -> None:
        self.path = Path(path)

    def append(self, attempt: Attempt) -> None:
        _append_line(self.path, attempt.model_dump_json())

    def read_all(self) -> list[Attempt]:
        return [Attempt.model_validate_json(line) for line in _read_lines(self.path)]

    def __len__(self) -> int:
        return sum(1 for _ in _read_lines(self.path))


class ModelCallLedger:
    """Append-only audit ledger of :class:`ModelCall` rows."""

    def __init__(self, path: str | Path = DEFAULT_MODEL_CALLS_PATH) -> None:
        self.path = Path(path)

    def append(self, call: ModelCall) -> None:
        _append_line(self.path, call.model_dump_json())

    def read_all(self) -> list[ModelCall]:
        return [ModelCall.model_validate_json(line) for line in _read_lines(self.path)]


__all__ = [
    "JSONLArchive",
    "ModelCallLedger",
    "DEFAULT_ATTEMPTS_PATH",
    "DEFAULT_MODEL_CALLS_PATH",
]
