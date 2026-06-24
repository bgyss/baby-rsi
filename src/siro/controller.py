"""Controller — the inner loop and candidate selection.

Goal 02 implements ``run_task``: the per-task improvement loop
(propose → sandbox → evaluate → archive → select). This *is* the inner loop of the
self-improvement cycle (``docs/13_self_improvement_loop.md``): every candidate —
passing or failing — is recorded; the best reproducible score is selected as the
seed for the next generation.

The controller, not any model, runs fixed vetted commands. Models only produce
proposals (text/patches); the controller writes them to the sandbox and runs the
fixed test suite (``docs/07_model_providers_and_tiers.md``).
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .archive import JSONLArchive, ModelCallLedger
from .evaluator import evaluate
from .memory import ResearchMemory
from .model_client import ModelClient, extract_code
from .prompts import load_prompt
from .sandbox import Sandbox
from .schemas import Attempt, AttemptStatus, Candidate, ModelCall, TaskSpec


@dataclass(frozen=True)
class LoadedTask:
    """A task loaded from disk: the prompt, seed code, and the *fixed* test suite.

    ``tests_path`` and ``module_name`` are what the sandbox uses; the candidate
    never supplies them, which is how "tests cannot be modified by the candidate"
    is enforced structurally rather than by trust.
    """

    spec: TaskSpec
    prompt: str
    seed_code: str
    tests_path: Path
    module_name: str

    @property
    def task_id(self) -> str:
        return self.spec.task_id


def load_task(task_dir: str | Path) -> LoadedTask:
    """Load a ``code_improver`` task directory (prompt.md, seed_solution.py, tests.py)."""
    path = Path(task_dir)
    prompt_path = path / "prompt.md"
    tests_path = path / "tests.py"
    seeds = sorted(p for p in path.glob("*.py") if p.name not in {"tests.py", "__init__.py"})
    if not prompt_path.exists() or not tests_path.exists() or not seeds:
        raise FileNotFoundError(
            f"Task dir {path} must contain prompt.md, tests.py, and a seed module."
        )
    seed_path = seeds[0]
    return LoadedTask(
        spec=TaskSpec(
            task_id=path.name,
            path=str(path),
            description=prompt_path.read_text(encoding="utf-8")
            .splitlines()[0]
            .lstrip("# ")
            .strip(),
        ),
        prompt=prompt_path.read_text(encoding="utf-8"),
        seed_code=seed_path.read_text(encoding="utf-8"),
        tests_path=tests_path,
        module_name=seed_path.stem,
    )


def select_best(attempts: list[Attempt]) -> Attempt | None:
    """Return the highest-scoring evaluated attempt, or ``None`` if there are none.

    Attempts without an evaluation (errors) are ignored for selection but remain in
    the archive as negative results.
    """
    scored = [a for a in attempts if a.evaluation is not None]
    if not scored:
        return None
    return max(scored, key=lambda a: a.evaluation.score)


@dataclass
class RunResult:
    """Outcome of one ``run_task`` invocation (for the CLI / callers)."""

    task_id: str
    attempts: list[Attempt] = field(default_factory=list)
    best: Attempt | None = None


def _short_id() -> str:
    return uuid.uuid4().hex[:12]


class Controller:
    """Drives the per-task improvement loop."""

    def __init__(
        self,
        archive: JSONLArchive | None = None,
        sandbox: Sandbox | None = None,
        ledger: ModelCallLedger | None = None,
        memory: ResearchMemory | None = None,
        prompts_dir: Path | None = None,
    ) -> None:
        # NB: use `is None`, not `or` — JSONLArchive/ResearchMemory define __len__, so
        # an empty store is falsy and an `or` default would silently discard a real one.
        self.archive = JSONLArchive() if archive is None else archive
        self.sandbox = Sandbox() if sandbox is None else sandbox
        self.ledger = ModelCallLedger() if ledger is None else ledger
        self.memory = ResearchMemory() if memory is None else memory
        self.prompts_dir = prompts_dir

    def best_so_far(self) -> Attempt | None:
        """Best attempt currently in the archive."""
        return select_best(self.archive.read_all())

    def _evaluate_candidate(self, candidate: Candidate, task: LoadedTask) -> Attempt:
        """Run a candidate through the sandbox + evaluator and build an Attempt."""
        sandbox_result = self.sandbox.run(candidate, task)
        evaluation = evaluate(sandbox_result, candidate.code)
        if sandbox_result.error:
            reason = sandbox_result.error
        elif sandbox_result.failed_tests:
            reason = f"{sandbox_result.failed_tests} test(s) failing"
        else:
            reason = "all tests passing"
        return Attempt(
            attempt_id=_short_id(),
            task_id=task.task_id,
            candidate=candidate,
            evaluation=evaluation,
            status=AttemptStatus.REJECTED,  # finalized by the caller against the best
            reason=reason,
        )

    def _persist(self, attempt: Attempt) -> None:
        """Archive an attempt and record it to research memory (controller-only writes)."""
        self.archive.append(attempt)
        self.memory.record(attempt)

    def _build_prompt(self, task: LoadedTask, current_code: str) -> str:
        template = load_prompt("code_improver", self.prompts_dir)
        # Memory lessons are *data*, not instructions: the prompt frames them as
        # untrusted reference and the task rules always take precedence.
        lessons = self.memory.lessons_block(task.task_id)
        return (
            template.replace("{task_prompt}", task.prompt)
            .replace("{module_name}", task.module_name)
            .replace("{current_code}", current_code.strip())
            .replace("{memory_lessons}", lessons or "- (no prior lessons yet)")
        )

    def _log_model_call(
        self, model: ModelClient, prompt: str, latency_ms: float, task_id: str
    ) -> None:
        self.ledger.append(
            ModelCall(
                provider=getattr(model, "provider", "unknown"),
                model=getattr(model, "model", "unknown"),
                prompt_hash=hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16],
                latency_ms=latency_ms,
                experiment_id=task_id,
            )
        )

    def run_task(
        self,
        task_dir: str | Path,
        model: ModelClient,
        generations: int = 5,
    ) -> RunResult:
        """Run the improvement loop for a task directory and return the best attempt.

        Generation 0 evaluates the seed as the baseline; each subsequent generation
        asks ``model`` for a replacement, scores it in the sandbox, archives it
        (passing *or* failing), and keeps the best reproducible candidate as the seed.
        """
        task = load_task(task_dir)
        result = RunResult(task_id=task.task_id)

        # Generation 0 — the seed is itself a candidate (the baseline to beat).
        seed = Candidate(candidate_id="seed", task_id=task.task_id, code=task.seed_code)
        baseline = self._evaluate_candidate(seed, task)
        baseline.status = (
            AttemptStatus.PROMOTED if baseline.evaluation.reproducible else AttemptStatus.ERROR
        )
        self._persist(baseline)
        result.attempts.append(baseline)
        best = baseline

        for _ in range(generations):
            prompt = self._build_prompt(task, best.candidate.code)
            start = time.perf_counter()
            raw = model.generate(prompt)
            latency_ms = (time.perf_counter() - start) * 1000.0
            self._log_model_call(model, prompt, latency_ms, task.task_id)

            candidate = Candidate(
                candidate_id=_short_id(),
                task_id=task.task_id,
                code=extract_code(raw),
                parent_id=best.candidate.candidate_id,
            )
            attempt = self._evaluate_candidate(candidate, task)

            if not attempt.evaluation.reproducible:
                attempt.status = AttemptStatus.ERROR
            elif attempt.evaluation.score > best.evaluation.score:
                attempt.status = AttemptStatus.PROMOTED
                best = attempt
            else:
                attempt.status = AttemptStatus.REJECTED

            self._persist(attempt)
            result.attempts.append(attempt)

        result.best = best
        return result


__all__ = ["LoadedTask", "load_task", "select_best", "RunResult", "Controller"]
