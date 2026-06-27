"""Research-shaped task suite + evaluation harness (Goal 09).

Goal 09 gives the Tier 1 organization *real work*: a suite of research-shaped tasks
(beyond single-function code repair) with objective, reproducible evaluators, so the
frontier agents are measured doing genuine research rather than templated mutation
(``docs/goal_prompts/goal_09_research_task_suite.md``). It is also the **fixed benchmark
the validate step of the self-improvement loop depends on** (``docs/13``): the held-fixed
A/B set both loops compare candidates and meta-changes against.

A research task lives in ``packs/<domain>/tasks/<family>/<task>/``::

    task.json   # machine metadata: family, edit surface, primary metric + direction
    brief.md    # objective, constraints, allowed edit surface, success metric (agent-visible)
    baseline/   # the starting code/config the org improves on (the edit surface + supports)
    eval.py     # the objective, reproducible evaluator — the *authority for promotion*
    hidden/     # optional held-out tests/data, never shown to agents (no-leakage)

The load-bearing invariants are enforced **structurally**, not by trust:

- ``eval.py`` is controller-owned and runs in the offline sandbox; a candidate cannot
  rewrite what scores it (the execution plane has no network, a scrubbed env, a hard
  timeout).
- The metric record ``eval.py`` returns is the authority for promotion — never a model's
  self-judgment. The *controller* decides promotion from it.
- Held-out data lives in ``hidden/`` and is handed to ``eval.py`` **outside** the
  candidate's working directory, via the ``SIRO_HIDDEN_PATH`` env var (see
  :meth:`Sandbox.run_research`); it never enters a model prompt, there is no relative file
  for the candidate to ``open``, and reading the env var or an absolute path from candidate
  code trips the static safety gate — so a metric gain cannot come from hidden-data leakage
  (enforced, not assumed).
- Promotion requires a *reproducible* improvement over the baseline; a lucky or noisy win
  cannot be promoted.

Expanding the benchmark scope or the compute/token budget is a human-gated change (the
bound in ``docs/13``): the suite here is the fixed set, and the budgets live in the
controller/config, never in a candidate.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from .memory import failure_signature
from .packs import DEFAULT_PACK_ID, DomainPack, EvaluatorAdapter, EvaluatorRegime, load_pack
from .sandbox import Sandbox
from .schemas import (
    AttemptStatus,
    Candidate,
    GateDecision,
    GateResult,
    MemoryEntry,
    MetricRecord,
    ResearchAttempt,
)

DEFAULT_RESEARCH_ATTEMPTS_PATH = Path("runs/research_attempts.jsonl")
DEFAULT_RESEARCH_TASKS_DIR = Path("packs/ml/tasks")

#: A candidate must beat the incumbent's primary metric by at least this (oriented so
#: larger is better) to count as an improvement — a guard against promoting on noise.
MIN_PRIMARY_IMPROVEMENT = 1e-9
#: Reruns of a promotion contender must agree on the primary metric within this tolerance.
REPRO_TOLERANCE = 1e-9
#: Default wall-clock budget for one evaluation, seconds (a *fixed* harness parameter).
DEFAULT_RESEARCH_BUDGET_SECONDS = 15.0


# --------------------------------------------------------------------------- #
# Task loading.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ResearchTask:
    """A research task loaded from disk.

    The evaluator (``eval_path``) and held-out data (``hidden_dir``) are *controller-owned*
    and are never placed in a model prompt — only ``brief`` and the baseline edit surface
    are agent-visible. ``primary_name``/``higher_is_better`` describe the metric direction
    so the same promotion logic works for higher-better (accuracy) and lower-better
    (validation loss, executed-line count) tasks.
    """

    task_id: str
    family: str
    path: str
    objective: str
    brief: str
    edit_surface: str
    surface_code: str
    support_files: dict[str, str]
    eval_path: Path
    hidden_dir: Path | None
    primary_name: str
    higher_is_better: bool
    budget_seconds: float
    pack_id: str = DEFAULT_PACK_ID
    pack_version: str = ""
    evaluator_regime: EvaluatorRegime = EvaluatorRegime.SEEDED_DETERMINISTIC
    evaluator_adapter: EvaluatorAdapter | None = None

    @property
    def allowed_surface(self) -> str:
        """The single path a candidate may edit (the agents' allow-listed edit surface)."""
        return str(Path(self.path) / "baseline" / self.edit_surface)


def _find_pack_for_task(path: Path) -> DomainPack:
    parts = path.resolve().parts
    if "packs" in parts:
        idx = len(parts) - 1 - parts[::-1].index("packs")
        if idx + 1 < len(parts):
            return load_pack(parts[idx + 1])
    return load_pack(DEFAULT_PACK_ID)


def load_research_task(task_dir: str | Path, *, pack: DomainPack | None = None) -> ResearchTask:
    """Load a research task directory (``task.json`` + ``brief.md`` + ``baseline/`` + ``eval.py``)."""
    path = Path(task_dir)
    pack = pack or _find_pack_for_task(path)
    meta_path = path / "task.json"
    brief_path = path / "brief.md"
    eval_path = path / "eval.py"
    baseline_dir = path / "baseline"
    if not meta_path.exists() or not brief_path.exists() or not eval_path.exists() or not baseline_dir.is_dir():
        raise FileNotFoundError(
            f"Research task dir {path} must contain task.json, brief.md, eval.py, and baseline/."
        )
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    edit_surface = meta["edit_surface"]
    surface_path = baseline_dir / edit_surface
    if not surface_path.exists():
        raise FileNotFoundError(f"Edit surface {surface_path} declared in task.json is missing.")
    support_files = {
        p.name: p.read_text(encoding="utf-8")
        for p in sorted(baseline_dir.iterdir())
        if p.is_file() and p.name != edit_surface
    }
    hidden_dir = path / "hidden"
    has_hidden = hidden_dir.is_dir() and any(hidden_dir.iterdir())
    return ResearchTask(
        task_id=path.name,
        family=meta.get("family", path.parent.name),
        path=str(path),
        objective=meta.get("objective", ""),
        brief=brief_path.read_text(encoding="utf-8"),
        edit_surface=edit_surface,
        surface_code=surface_path.read_text(encoding="utf-8"),
        support_files=support_files,
        eval_path=eval_path,
        hidden_dir=hidden_dir if has_hidden else None,
        primary_name=meta.get("primary_metric", "primary"),
        higher_is_better=bool(meta.get("higher_is_better", True)),
        budget_seconds=float(meta.get("budget_seconds", DEFAULT_RESEARCH_BUDGET_SECONDS)),
        pack_id=pack.id,
        pack_version=pack.version,
        evaluator_regime=pack.regime,
        evaluator_adapter=pack.adapter,
    )


def discover_research_tasks(
    root: str | Path | None = DEFAULT_RESEARCH_TASKS_DIR, *, pack_id: str | None = None
) -> list[ResearchTask]:
    """Load every research task under ``root`` (a directory with a ``task.json``)."""
    pack = load_pack(pack_id or DEFAULT_PACK_ID)
    base = pack.tasks_dir if root is None else Path(root)
    if not base.is_dir():
        return []
    tasks: list[ResearchTask] = []
    for meta in sorted(base.rglob("task.json")):
        tasks.append(load_research_task(meta.parent, pack=pack))
    return tasks


def hidden_payload(task: ResearchTask) -> str | None:
    """Serialize the held-out data for ``eval.py`` (read by the controller, not the model).

    Merges every ``*.json`` file under ``hidden/`` into one object keyed by file stem (so
    ``hidden/benchmark.json`` becomes ``{"benchmark": ...}``). The sandbox writes this
    outside the candidate's working directory and points ``eval.py`` at it via
    ``SIRO_HIDDEN_PATH``. This is the only path the held-out data takes; it never reaches a
    prompt nor the candidate's cwd.
    """
    if task.hidden_dir is None:
        return None
    merged: dict[str, object] = {}
    for p in sorted(task.hidden_dir.glob("*.json")):
        merged[p.stem] = json.loads(p.read_text(encoding="utf-8"))
    if not merged:
        return None
    return json.dumps(merged)


# --------------------------------------------------------------------------- #
# Evaluation harness — eval.py is the authority for promotion.
# --------------------------------------------------------------------------- #


def _run_eval_py(task: ResearchTask, candidate_code: str, sandbox: Sandbox) -> MetricRecord:
    """Run the task's fixed ``eval.py`` against ``candidate_code`` and return its metric.

    The candidate supplies only its edited edit surface; ``eval.py`` (controller-owned) and
    the held-out data are copied in by the sandbox. The returned :class:`MetricRecord` is
    the objective authority the controller promotes on.
    """
    files = {task.edit_surface: candidate_code, **task.support_files}
    run = sandbox.run_research(
        task.eval_path,
        files,
        hidden_payload=hidden_payload(task),
        budget_seconds=task.budget_seconds,
    )
    if not run.ran:
        return MetricRecord(
            primary_name=task.primary_name,
            higher_is_better=task.higher_is_better,
            passed=False,
            reproducible=False,
            error=run.error or "eval.py produced no metric record",
        )
    m = run.metrics
    secondary = {k: float(v) for k, v in (m.get("secondary") or {}).items()}
    return MetricRecord(
        primary_name=task.primary_name,
        primary=float(m["primary"]),
        higher_is_better=task.higher_is_better,
        passed=bool(m.get("passed", False)),
        secondary=secondary,
        reproducible=True,
        notes=str(m.get("notes", "")),
    )


def run_research_eval(task: ResearchTask, candidate_code: str, sandbox: Sandbox) -> MetricRecord:
    """Score a candidate through the task's pack-declared evaluator adapter."""
    adapter = task.evaluator_adapter
    if adapter is None:
        adapter = load_pack(task.pack_id).adapter
    return adapter.evaluate(task, candidate_code, sandbox)


def research_improves(candidate: MetricRecord, baseline: MetricRecord) -> tuple[bool, str]:
    """Whether ``candidate`` is an objective improvement over ``baseline`` (deterministic).

    A candidate must first satisfy the correctness/success precondition (``passed``); a
    candidate that fails it can never be promoted, regardless of its primary value (this is
    what stops a "fast but wrong" or loophole candidate from winning). Among passing
    candidates the primary metric — oriented so larger is always better — must strictly
    improve by :data:`MIN_PRIMARY_IMPROVEMENT`. If the baseline itself does not pass, any
    passing candidate is an improvement.
    """
    name = candidate.primary_name
    if not candidate.passed:
        return False, "candidate failed the correctness/success precondition"
    if not baseline.passed:
        return True, "candidate passes where baseline did not"
    delta = candidate.directional() - baseline.directional()
    if delta > MIN_PRIMARY_IMPROVEMENT:
        return True, f"{name} {baseline.primary:g} -> {candidate.primary:g}"
    if (
        name == "proof_verified"
        and abs(delta) <= MIN_PRIMARY_IMPROVEMENT
        and candidate.passed
        and baseline.passed
    ):
        for secondary_name in ("proof_length", "dependency_count"):
            if secondary_name not in candidate.secondary or secondary_name not in baseline.secondary:
                continue
            before = baseline.secondary[secondary_name]
            after = candidate.secondary[secondary_name]
            if before - after > MIN_PRIMARY_IMPROVEMENT:
                return True, f"{secondary_name} {before:g} -> {after:g}"
    return False, f"no improvement on {name} ({baseline.primary:g} -> {candidate.primary:g})"


def research_reproducibility_gate(
    task: ResearchTask, candidate_code: str, sandbox: Sandbox, *, runs: int = 2
) -> GateResult:
    """Rerun a promotion contender and require it reproduces the same primary metric.

    A candidate whose metric is not reproducible — because it failed to run on a rerun or
    drifted past tolerance — fails and is never promoted (Goal 09: "reproducible across
    reruns before promotion"). The seeded benchmarks are deterministic, so honest reruns
    agree exactly.
    """
    if task.evaluator_regime is EvaluatorRegime.STATISTICAL:
        return GateResult(
            gate="research_reproducibility",
            decision=GateDecision.FAILED,
            risk_level="high",
            findings=["statistical evaluator regime is declared but unsupported until Goal 24"],
        )
    runs = max(runs, 2)
    metrics = [run_research_eval(task, candidate_code, sandbox) for _ in range(runs)]
    if not all(m.passed and m.reproducible for m in metrics):
        return GateResult(
            gate="research_reproducibility",
            decision=GateDecision.FAILED,
            risk_level="medium",
            findings=["candidate did not produce a passing metric on every rerun"],
        )
    primaries = [round(m.primary, 12) for m in metrics]
    if max(primaries) - min(primaries) > REPRO_TOLERANCE:
        return GateResult(
            gate="research_reproducibility",
            decision=GateDecision.FAILED,
            risk_level="high",
            findings=[f"primary metric not reproducible across reruns: {primaries}"],
        )
    return GateResult(
        gate="research_reproducibility",
        decision=GateDecision.PASSED,
        risk_level="low",
        notes=f"{runs} reruns consistent at {task.primary_name}={primaries[0]:g}",
    )


# --------------------------------------------------------------------------- #
# Archive + memory derivation.
# --------------------------------------------------------------------------- #


def _read_lines(path: Path) -> Iterator[str]:
    if not path.exists():
        return iter(())
    with path.open("r", encoding="utf-8") as fh:
        return iter([line for line in (raw.strip() for raw in fh) if line])


class ResearchArchive:
    """Append-only JSONL archive of :class:`ResearchAttempt`s — separate from code attempts.

    Kept in its own file (``runs/research_attempts.jsonl``) so a research attempt is never
    confused with a code or training attempt, and every candidate tried — promoted or
    rejected — stays auditable.
    """

    def __init__(self, path: str | Path = DEFAULT_RESEARCH_ATTEMPTS_PATH) -> None:
        self.path = Path(path)

    def append(self, attempt: ResearchAttempt) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(attempt.model_dump_json() + "\n")

    def read_all(self) -> list[ResearchAttempt]:
        return [ResearchAttempt.model_validate_json(line) for line in _read_lines(self.path)]

    def __len__(self) -> int:
        return sum(1 for _ in _read_lines(self.path))


def _candidate_summary(code: str) -> str:
    for line in code.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:120]
    return ""


def entry_from_research_attempt(attempt: ResearchAttempt) -> MemoryEntry:
    """Derive a typed :class:`MemoryEntry` from a research attempt (controller-only write).

    The only path from a research attempt into memory; it runs in the controller, never a
    model. The metric becomes a directional ``score`` (larger is better) so memory's
    highest-scoring retrieval works uniformly across families.
    """
    metric = attempt.metric
    signature = failure_signature(attempt.reason)
    if metric is None:
        evaluator_output = "no evaluation"
        score = 0.0
    else:
        evaluator_output = (
            f"{metric.primary_name}={metric.primary:g} passed={metric.passed} "
            f"reproducible={metric.reproducible}"
        )
        score = metric.directional() if metric.passed else 0.0
    return MemoryEntry(
        entry_id=uuid.uuid4().hex[:12],
        experiment_id=attempt.attempt_id,
        source_experiment_id=attempt.candidate.parent_id or "",
        task_id=attempt.task_id,
        pack_id=attempt.pack_id,
        pack_version=attempt.pack_version,
        candidate_summary=_candidate_summary(attempt.candidate.code),
        score=score,
        failure_mode=signature,
        reason=attempt.reason,
        evaluator_output=evaluator_output,
        status=attempt.status,
        created_at=attempt.created_at,
    )


# --------------------------------------------------------------------------- #
# Suite summary — per task family.
# --------------------------------------------------------------------------- #


@dataclass
class ResearchFamilySummary:
    """Aggregate progress for one task family (Goal 09 acceptance: the summary command)."""

    family: str
    task_ids: list[str] = field(default_factory=list)
    attempts: int = 0
    accepted: int = 0
    promoted: int = 0
    mixed: int = 0
    failed: int = 0
    pass_rate: float = 0.0
    median_cycles_to_success: float | None = None
    safety_gate_failures: int = 0
    hidden_test_failures: int = 0
    reproducibility_failures: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    cost_per_promotion: float | None = None
    strategy_diversity: float = 0.0


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _cycles_to_success(attempts: list[ResearchAttempt]) -> int | None:
    """Number of attempts up to and including the first promotion, or ``None`` if never."""
    for i, a in enumerate(attempts, start=1):
        if a.status is AttemptStatus.PROMOTED:
            return i
    return None


def _has_safety_gate_failure(attempt: ResearchAttempt) -> bool:
    if attempt.gates is None:
        return False
    return any(
        r.gate == "safety" and r.decision is not GateDecision.PASSED for r in attempt.gates.results
    )


def _has_gate_failure(attempt: ResearchAttempt, needle: str) -> bool:
    if attempt.gates is None:
        return False
    return any(
        needle in r.gate and r.decision is not GateDecision.PASSED for r in attempt.gates.results
    )


def summarize_research(
    attempts: list[ResearchAttempt], ledger_rows=None
) -> dict[str, ResearchFamilySummary]:
    """Summarize the research-attempt archive per task family.

    Reports, per family: pass rate, median cycles to success, safety-gate failures,
    token/USD spend, and strategy diversity (Goal 09 acceptance criteria). ``ledger_rows``
    is the model-call audit ledger (:class:`~siro.schemas.ModelCall`); spend is attributed
    to a family by matching each row's ``experiment_id`` to the family's task ids.
    """
    by_family: dict[str, list[ResearchAttempt]] = {}
    for a in attempts:
        by_family.setdefault(a.family or "(unknown)", []).append(a)

    # task_id -> family, to attribute ledger spend.
    task_family = {a.task_id: (a.family or "(unknown)") for a in attempts}
    spend: dict[str, tuple[int, float]] = {}
    for row in ledger_rows or []:
        fam = task_family.get(row.experiment_id)
        if fam is None:
            continue
        tokens, cost = spend.get(fam, (0, 0.0))
        spend[fam] = (tokens + row.input_tokens + row.output_tokens, cost + row.cost_usd)

    summaries: dict[str, ResearchFamilySummary] = {}
    for family, fam_attempts in sorted(by_family.items()):
        task_ids = sorted({a.task_id for a in fam_attempts})
        n = len(fam_attempts)
        passed = sum(1 for a in fam_attempts if a.metric is not None and a.metric.passed)
        promoted = sum(1 for a in fam_attempts if a.status is AttemptStatus.PROMOTED)
        errors = sum(1 for a in fam_attempts if a.status is AttemptStatus.ERROR)
        rejected = sum(1 for a in fam_attempts if a.status is AttemptStatus.REJECTED)
        mixed = sum(
            1
            for a in fam_attempts
            if a.status is AttemptStatus.REJECTED and a.metric is not None and a.metric.passed
        )

        cycles: list[float] = []
        for task_id in task_ids:
            ta = [a for a in fam_attempts if a.task_id == task_id]
            c = _cycles_to_success(ta)
            if c is not None:
                cycles.append(float(c))

        distinct = len({a.candidate.code for a in fam_attempts})
        tokens, cost = spend.get(family, (0, 0.0))
        summaries[family] = ResearchFamilySummary(
            family=family,
            task_ids=task_ids,
            attempts=n,
            accepted=promoted,
            promoted=promoted,
            mixed=mixed,
            failed=rejected + errors - mixed,
            pass_rate=(passed / n) if n else 0.0,
            median_cycles_to_success=_median(cycles) if cycles else None,
            safety_gate_failures=sum(1 for a in fam_attempts if _has_safety_gate_failure(a)),
            hidden_test_failures=sum(
                1
                for a in fam_attempts
                if _has_gate_failure(a, "hidden") or "hidden" in a.reason.lower()
            ),
            reproducibility_failures=sum(
                1
                for a in fam_attempts
                if _has_gate_failure(a, "reproducibility")
                or "reproduc" in a.reason.lower()
                or (a.metric is not None and a.metric.passed and not a.metric.reproducible)
            ),
            tokens=tokens,
            cost_usd=cost,
            cost_per_promotion=(cost / promoted) if promoted else None,
            strategy_diversity=(distinct / n) if n else 0.0,
        )
    return summaries


def select_best_research(attempts: list[ResearchAttempt]) -> ResearchAttempt | None:
    """Return the best passing, reproducible attempt (highest directional primary), or None."""
    scored = [
        a for a in attempts if a.metric is not None and a.metric.passed and a.metric.reproducible
    ]
    if not scored:
        return None
    return max(scored, key=lambda a: a.metric.directional())


def make_candidate(task: ResearchTask, code: str, parent_id: str = "seed") -> Candidate:
    """Build a :class:`Candidate` for a research task's edit surface."""
    return Candidate(
        candidate_id=uuid.uuid4().hex[:12], task_id=task.task_id, code=code, parent_id=parent_id
    )


__all__ = [
    "DEFAULT_RESEARCH_ATTEMPTS_PATH",
    "DEFAULT_RESEARCH_TASKS_DIR",
    "DEFAULT_RESEARCH_BUDGET_SECONDS",
    "MIN_PRIMARY_IMPROVEMENT",
    "REPRO_TOLERANCE",
    "ResearchTask",
    "load_research_task",
    "discover_research_tasks",
    "hidden_payload",
    "run_research_eval",
    "research_improves",
    "research_reproducibility_gate",
    "ResearchArchive",
    "entry_from_research_attempt",
    "ResearchFamilySummary",
    "summarize_research",
    "select_best_research",
    "make_candidate",
]
