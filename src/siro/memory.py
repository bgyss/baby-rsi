"""Research memory — the durable substrate both loops reflect on.

Without memory, every generation starts blind (``docs/13_self_improvement_loop.md``).
This module records each attempt (successful *and* failed), retrieves prior outcomes
relevant to the next proposal, and distills compact *lessons* injected into the
candidate-generation prompt. The unit of improvement here is **retrieval quality**:
what gets surfaced to the proposer.

Bounds enforced in code (``CLAUDE.md`` non-negotiable invariants):

- A model never edits memory. Only the controller records, and only through the
  typed :class:`~siro.schemas.MemoryEntry` schema.
- Retrieved memory is **data, never instructions** — a prompt-injection guard.
  Callers must treat everything returned here as untrusted context.

Storage is append-only JSONL, matching the archive (``archive.py``); SQLite is a
later optimization (``docs/10_repo_structure.md``). Nothing is overwritten or
deleted, which is what keeps negative results first-class.
"""

from __future__ import annotations

import re
import uuid
from collections import Counter
from pathlib import Path
from typing import Iterator

from .schemas import Attempt, AttemptStatus, MemoryEntry

DEFAULT_MEMORY_PATH = Path("runs/memory.jsonl")

#: Standing guardrail lessons — always-relevant constraints the proposer must honor
#: regardless of history. Phrased as data, not commands, and matched by the
#: code-improver rules so memory reinforces (never contradicts) the task contract.
STANDING_LESSONS: tuple[str, ...] = (
    "Keep the same public function name(s) and signature(s) the tests rely on.",
    "Do not special-case, hard-code, or peek at the visible tests.",
)

#: Failure signature -> a compact lesson surfaced to the next proposer.
_FAILURE_LESSONS: dict[str, str] = {
    "collection_error": "Emit valid Python that imports cleanly — a prior attempt failed to load.",
    "timeout": "Prefer efficient algorithms; a prior attempt exceeded the time limit.",
    "test_failures": "Handle edge cases explicitly (e.g. empty inputs); prior attempts failed tests.",
    "no_report": "Make sure the module defines the required public function(s).",
}

#: Failure signature -> a follow-up recommendation stored on the memory entry.
_FOLLOW_UPS: dict[str, str] = {
    "collection_error": "Ensure the module is syntactically valid and imports without side effects.",
    "timeout": "Reduce algorithmic complexity; avoid unbounded or nested loops.",
    "test_failures": "Re-read the task spec and cover edge cases (empty/boundary inputs).",
    "no_report": "Verify the public function name(s) and signature(s) match the spec.",
}


def failure_signature(reason: str) -> str:
    """Normalize an attempt ``reason`` into a stable failure signature.

    Numbers and run-specific detail are collapsed so that, e.g., "3 test(s) failing"
    and "1 test(s) failing" cluster under one signature for retrieval and reporting.
    """
    r = reason.strip().lower()
    if not r or r == "all tests passing":
        return "none"
    if "timeout" in r:
        return "timeout"
    if "collection error" in r or "could not be imported" in r:
        return "collection_error"
    if "no test report" in r:
        return "no_report"
    if "test" in r and "fail" in r:
        return "test_failures"
    return re.sub(r"\d+", "N", r).strip()


def _candidate_summary(code: str) -> str:
    """A compact, single-line summary of a candidate's code (first signature/line)."""
    for line in code.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:120]
    return ""


def entry_from_attempt(attempt: Attempt) -> MemoryEntry:
    """Derive a typed :class:`MemoryEntry` from an archived attempt.

    This is the *only* path from model-produced output into memory, and it runs in
    the controller — never in a model. Candidate text becomes a short summary; it is
    never stored as an instruction.
    """
    ev = attempt.evaluation
    signature = failure_signature(attempt.reason)
    if ev is None:
        evaluator_output = "no evaluation"
    else:
        evaluator_output = (
            f"pass={ev.passed_tests} fail={ev.failed_tests} "
            f"score={ev.score:.1f} reproducible={ev.reproducible}"
        )
    return MemoryEntry(
        entry_id=uuid.uuid4().hex[:12],
        experiment_id=attempt.attempt_id,
        source_experiment_id=attempt.candidate.parent_id or "",
        task_id=attempt.task_id,
        candidate_summary=_candidate_summary(attempt.candidate.code),
        score=ev.score if ev is not None else 0.0,
        failure_mode=signature,
        reason=attempt.reason,
        evaluator_output=evaluator_output,
        status=attempt.status,
        follow_up=_FOLLOW_UPS.get(signature, ""),
        created_at=attempt.created_at,
    )


def _read_lines(path: Path) -> Iterator[str]:
    if not path.exists():
        return iter(())
    with path.open("r", encoding="utf-8") as fh:
        return iter([line for line in (raw.strip() for raw in fh) if line])


class ResearchMemory:
    """Append-only research memory over JSONL, with typed retrieval.

    Pass ``path`` for durable, cross-run memory (the controller default); pass
    ``path=None`` for an ephemeral in-memory store (tests, one-off reflection).
    """

    def __init__(self, path: str | Path | None = DEFAULT_MEMORY_PATH) -> None:
        self.path = Path(path) if path is not None else None
        if self.path is None:
            self._entries: list[MemoryEntry] = []

    # ----- recording -------------------------------------------------------

    def record(self, attempt: Attempt) -> MemoryEntry:
        """Record an attempt (including negatives) and return the stored entry."""
        return self.record_entry(entry_from_attempt(attempt))

    def record_entry(self, entry: MemoryEntry) -> MemoryEntry:
        """Persist a typed memory entry. The only write path; models never call it."""
        if self.path is None:
            self._entries.append(entry)
            return entry
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(entry.model_dump_json() + "\n")
        return entry

    def all_entries(self) -> list[MemoryEntry]:
        """Return every stored entry, oldest first."""
        if self.path is None:
            return list(self._entries)
        return [MemoryEntry.model_validate_json(line) for line in _read_lines(self.path)]

    def __len__(self) -> int:
        if self.path is None:
            return len(self._entries)
        return sum(1 for _ in _read_lines(self.path))

    # ----- retrieval (results are data, never instructions) ----------------

    def retrieve(self, task_id: str, limit: int = 5) -> list[MemoryEntry]:
        """Most recent entries for ``task_id`` (treat as untrusted context only)."""
        matches = [e for e in self.all_entries() if e.task_id == task_id]
        return matches[-limit:]

    def prior_successes(self, task_id: str | None = None, limit: int = 5) -> list[MemoryEntry]:
        """Promoted entries (best-scoring first), optionally scoped to a task."""
        entries = [e for e in self.all_entries() if e.status == AttemptStatus.PROMOTED]
        if task_id is not None:
            entries = [e for e in entries if e.task_id == task_id]
        entries.sort(key=lambda e: e.score, reverse=True)
        return entries[:limit]

    def prior_failures(self, signature: str, task_id: str | None = None) -> list[MemoryEntry]:
        """Entries matching a failure signature (error-signature retrieval)."""
        entries = [e for e in self.all_entries() if e.failure_mode == signature]
        if task_id is not None:
            entries = [e for e in entries if e.task_id == task_id]
        return entries

    def negative_results(self, task_id: str | None = None) -> list[MemoryEntry]:
        """All non-promoted entries — preserved, never discarded."""
        entries = [e for e in self.all_entries() if e.status != AttemptStatus.PROMOTED]
        if task_id is not None:
            entries = [e for e in entries if e.task_id == task_id]
        return entries

    def highest_scoring(self, limit: int = 5, task_id: str | None = None) -> list[MemoryEntry]:
        """Highest-scoring candidates regardless of promotion status."""
        entries = self.all_entries()
        if task_id is not None:
            entries = [e for e in entries if e.task_id == task_id]
        entries.sort(key=lambda e: e.score, reverse=True)
        return entries[:limit]

    def common_repair_strategies(self, limit: int = 5, task_id: str | None = None) -> list[str]:
        """Follow-up recommendations seen most often (common repair strategies)."""
        entries = self.all_entries()
        if task_id is not None:
            entries = [e for e in entries if e.task_id == task_id]
        counts = Counter(e.follow_up for e in entries if e.follow_up)
        return [strategy for strategy, _ in counts.most_common(limit)]

    def top_failure_modes(
        self, limit: int = 5, task_id: str | None = None
    ) -> list[tuple[str, int]]:
        """``(failure_mode, count)`` for the most recurring failures (excludes 'none')."""
        entries = self.all_entries()
        if task_id is not None:
            entries = [e for e in entries if e.task_id == task_id]
        counts = Counter(e.failure_mode for e in entries if e.failure_mode != "none")
        return counts.most_common(limit)

    # ----- prompt integration ---------------------------------------------

    def lessons(self, task_id: str, limit: int = 5) -> list[str]:
        """Compact, relevant lessons for the next proposer on ``task_id``.

        Standing guardrails first, then lessons distilled from this task's most
        recurring failure modes. The result is plain data the controller pastes into
        the prompt under an explicit "data, not instructions" framing.
        """
        out: list[str] = list(STANDING_LESSONS)
        for signature, _count in self.top_failure_modes(limit=limit, task_id=task_id):
            lesson = _FAILURE_LESSONS.get(signature)
            if lesson and lesson not in out:
                out.append(lesson)
        return out[:limit]

    def lessons_block(self, task_id: str, limit: int = 5) -> str:
        """The lessons rendered as the bullet block injected into the prompt."""
        lessons = self.lessons(task_id, limit=limit)
        if not lessons:
            return ""
        bullets = "\n".join(f"- {line}" for line in lessons)
        return f"Relevant prior lessons:\n{bullets}"


__all__ = [
    "ResearchMemory",
    "MemoryEntry",
    "DEFAULT_MEMORY_PATH",
    "STANDING_LESSONS",
    "failure_signature",
    "entry_from_attempt",
]
