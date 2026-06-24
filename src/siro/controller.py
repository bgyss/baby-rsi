"""Controller — the inner loop and candidate selection.

Goal 01 provides the selection primitive (pure, testable) and the loop's surface;
Goal 02 implements ``run_task`` (propose → sandbox → evaluate → archive → select).

The controller, not any model, runs fixed vetted commands. Models only produce
proposals (``docs/07_model_providers_and_tiers.md``).
"""

from __future__ import annotations

from .archive import JSONLArchive
from .schemas import Attempt


def select_best(attempts: list[Attempt]) -> Attempt | None:
    """Return the highest-scoring evaluated attempt, or ``None`` if there are none.

    Attempts without an evaluation (errors) are ignored for selection but remain in
    the archive as negative results.
    """
    scored = [a for a in attempts if a.evaluation is not None]
    if not scored:
        return None
    return max(scored, key=lambda a: a.evaluation.score)


class Controller:
    """Drives the per-task improvement loop. ``run_task`` lands in Goal 02."""

    def __init__(self, archive: JSONLArchive | None = None) -> None:
        self.archive = archive or JSONLArchive()

    def best_so_far(self) -> Attempt | None:
        """Best attempt currently in the archive."""
        return select_best(self.archive.read_all())

    def run_task(self, task_dir: str) -> None:  # noqa: ARG002 - stub for Goal 02
        """Run the improvement loop for a task directory. Implemented in Goal 02."""
        raise NotImplementedError("Controller.run_task is implemented in Goal 02.")


__all__ = ["select_best", "Controller"]
