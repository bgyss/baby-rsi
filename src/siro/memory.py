"""Research memory — durable substrate both loops reflect on.

Goal 01 provides the interface only; Goal 03 implements structured storage,
retrieval, and failure clustering. Defined now so later goals (and the CLI) can
depend on a stable surface.

Invariant (``docs/13_self_improvement_loop.md``): retrieved memory is **data,
never instructions** — a prompt-injection guard. Callers must treat anything
returned here as untrusted context, not as commands.
"""

from __future__ import annotations

from .schemas import Attempt


class ResearchMemory:
    """Stub memory store. Goal 03 fills storage + retrieval."""

    def __init__(self) -> None:
        self._attempts: list[Attempt] = []

    def record(self, attempt: Attempt) -> None:
        """Record an attempt (including negatives) for later retrieval."""
        self._attempts.append(attempt)

    def retrieve(self, task_id: str, limit: int = 5) -> list[Attempt]:
        """Return prior attempts relevant to ``task_id``. Treat results as data only."""
        matches = [a for a in self._attempts if a.task_id == task_id]
        return matches[-limit:]


__all__ = ["ResearchMemory"]
