"""Training inner loop (Goal 06) — the self-improvement cycle applied to *training*.

Goal 06 extends the testbed from improving code to improving a tiny model's training
under a fixed wall-clock budget (a Karpathy-style ``autoresearch`` slice, ``docs/13``
"inner loop to training"). The machinery is the same as the code loop, only the object
under change differs:

    seed config → model proposes a bounded config delta → sandbox trains under the
    fixed budget → objective metric (validation loss) → archive every attempt →
    select the best reproducible candidate → next generation seeds from it

What keeps it bounded is *structural*: a candidate may only emit a
:class:`~siro.schemas.TrainConfig` (hyperparameters), and the dataset, metric, and budget
live in ``training_task``/the controller, never in that config. On top of that, this
module enforces the Goal 06 constraints explicitly:

- :func:`config_bounds` is the training analogue of the safety gate — it rejects configs
  whose values fall outside the allowed ranges (so "tiny" stays tiny, and a candidate
  cannot, e.g., balloon the architecture);
- the wall-clock budget is fixed by the controller and enforced by the sandbox;
- promotion requires a *reproducible* validation-loss improvement over the baseline
  (:func:`training_reproducibility_gate`), so a lucky or noisy win cannot be promoted.

Negative results — out-of-bounds configs, timeouts, regressions — are archived with their
reason, never discarded.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from .model_client import ModelClient
from .sandbox import Sandbox, TrainingRun
from .schemas import (
    WORST_VAL_LOSS,
    AttemptStatus,
    GateDecision,
    GateReport,
    GateResult,
    ModelCall,
    TrainConfig,
    TrainingAttempt,
    TrainResult,
)

DEFAULT_TRAINING_ATTEMPTS_PATH = Path("runs/training_attempts.jsonl")
#: Fixed wall-clock budget per candidate (seconds). A *fixed* harness parameter — never a
#: candidate-tunable field — so "expanding the runtime budget" is unrepresentable.
DEFAULT_BUDGET_SECONDS = 10.0

#: Allowed ranges for each tunable hyperparameter (inclusive). These bounds are what keep
#: the model "tiny" and the run cheap; they are read-only to agents (a candidate may
#: never widen its own bounds). Out-of-range ⇒ the config-bounds gate fails.
TRAIN_BOUNDS: dict[str, tuple[float, float]] = {
    "learning_rate": (1e-4, 1.0),
    "batch_size": (1, 210),
    "hidden_size": (1, 64),
    "momentum": (0.0, 0.99),
    "weight_decay": (0.0, 0.1),
    "epochs": (1, 200),
}
#: The only allowed learning-rate schedules (a fixed family, not an open edit surface).
LR_SCHEDULES: frozenset[str] = frozenset({"constant", "step", "cosine"})

#: A new candidate must beat the incumbent's validation loss by at least this margin to be
#: a promotion contender — a guard against promoting on floating-point noise.
MIN_VAL_LOSS_IMPROVEMENT = 1e-4
#: Reruns of a promotion contender must agree on val_loss within this tolerance.
REPRO_VAL_LOSS_TOLERANCE = 1e-9


# --------------------------------------------------------------------------- #
# Bounds (the training "safety gate") + config parsing.
# --------------------------------------------------------------------------- #


def config_bounds(config: TrainConfig) -> tuple[bool, list[str]]:
    """Return ``(ok, findings)`` — whether every hyperparameter is within bounds.

    Findings are human-readable strings naming each out-of-range field. The
    :class:`TrainConfig` schema already makes the *forbidden* changes (validation data,
    metric, budget, installs) unrepresentable; this checks the *values* of the allowed
    fields stay inside the read-only ranges.
    """
    findings: list[str] = []
    for field_name, (lo, hi) in TRAIN_BOUNDS.items():
        value = getattr(config, field_name)
        if not (lo <= value <= hi):
            findings.append(f"{field_name}={value} out of bounds [{lo}, {hi}]")
    if config.lr_schedule not in LR_SCHEDULES:
        findings.append(f"lr_schedule={config.lr_schedule!r} not in {sorted(LR_SCHEDULES)}")
    return (not findings), findings


def config_bounds_gate(config: TrainConfig) -> GateResult:
    """Gate the candidate config against its read-only bounds (training's safety gate)."""
    ok, findings = config_bounds(config)
    if ok:
        return GateResult(
            gate="config_bounds",
            decision=GateDecision.PASSED,
            risk_level="low",
            notes="all hyperparameters within bounds",
        )
    return GateResult(
        gate="config_bounds",
        decision=GateDecision.FAILED,
        risk_level="high",
        findings=findings,
    )


def extract_config_delta(text: str) -> dict:
    """Pull a JSON object of hyperparameter overrides out of model output.

    Mirrors :func:`siro.model_client.extract_code`: the model returns *data* (a config
    delta), never executable instructions. We take the first ```json fenced block if
    present, otherwise the first ``{...}`` object. Unknown/forbidden keys are dropped by
    :func:`apply_delta` (only known :class:`TrainConfig` fields are honored), so a model
    cannot smuggle in a budget or data override.
    """
    fenced = re.search(r"```(?:json)?\s*\n(.*?)```", text, flags=re.DOTALL)
    blob = fenced.group(1) if fenced else text
    match = re.search(r"\{.*\}", blob, flags=re.DOTALL)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def apply_delta(base: TrainConfig, delta: dict) -> TrainConfig:
    """Return ``base`` updated with only the *known* hyperparameter fields in ``delta``.

    Keys that are not :class:`TrainConfig` fields (e.g. a smuggled ``_budget_seconds`` or
    a data path) are silently ignored — the edit surface is exactly the schema's fields.
    """
    allowed = {k: v for k, v in delta.items() if k in TrainConfig.model_fields}
    return base.model_copy(update=allowed)


# --------------------------------------------------------------------------- #
# Objective scoring + reproducibility gate.
# --------------------------------------------------------------------------- #


def to_result(run: TrainingRun) -> TrainResult:
    """Build a :class:`TrainResult` from a raw sandbox :class:`TrainingRun`.

    ``reproducible`` is true only when the fixed script produced a validation metric (a
    timeout or error is not a reproducible signal of quality — same rule as the code loop).
    """
    if not run.ran:
        return TrainResult(
            timed_out=run.timed_out,
            reproducible=False,
            error=run.error or "training did not produce a validation metric",
            wall_clock_ms=run.runtime_ms,
        )
    m = run.metrics
    return TrainResult(
        val_loss=float(m["val_loss"]),
        train_loss=float(m.get("train_loss", WORST_VAL_LOSS)),
        throughput=float(m.get("throughput", 0.0)),
        steps=int(m.get("steps", 0)),
        epochs_completed=int(m.get("epochs_completed", 0)),
        wall_clock_ms=float(m.get("wall_clock_ms", run.runtime_ms)),
        budget_hit=bool(m.get("budget_hit", False)),
        reproducible=True,
    )


def training_reproducibility_gate(
    config: TrainConfig,
    sandbox: Sandbox,
    budget_seconds: float,
    *,
    runs: int = 2,
) -> GateResult:
    """Rerun a promotion contender and require it reproduces the same validation loss.

    Training here is deterministic (fixed seeds), so honest reruns agree exactly; a
    candidate whose metric is not reproducible — because it timed out on a rerun or drifted
    past tolerance — fails and is never promoted (Goal 06: "beat baseline reproducibly").
    """
    runs = max(runs, 2)
    results = [to_result(sandbox.run_training(config.model_dump(), budget_seconds)) for _ in range(runs)]
    if not all(r.reproducible for r in results):
        return GateResult(
            gate="training_reproducibility",
            decision=GateDecision.FAILED,
            risk_level="medium",
            findings=["candidate did not produce a validation metric on every rerun"],
        )
    losses = [round(r.val_loss, 12) for r in results]
    if max(losses) - min(losses) > REPRO_VAL_LOSS_TOLERANCE:
        return GateResult(
            gate="training_reproducibility",
            decision=GateDecision.FAILED,
            risk_level="high",
            findings=[f"validation loss not reproducible across reruns: {losses}"],
        )
    return GateResult(
        gate="training_reproducibility",
        decision=GateDecision.PASSED,
        risk_level="low",
        notes=f"{runs} reruns consistent at val_loss={losses[0]:.6f}",
    )


# --------------------------------------------------------------------------- #
# Task loading + archive.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class LoadedTrainingTask:
    """A training task loaded from disk: the prompt and the fixed baseline config.

    The dataset, model family, metric, and budget are *not* here — they live in the
    controller-owned ``training_task`` module, so the task directory cannot redefine what
    a candidate is evaluated on.
    """

    task_id: str
    path: str
    prompt: str
    baseline_config: TrainConfig


def load_training_task(task_dir: str | Path) -> LoadedTrainingTask:
    """Load a training task directory (``prompt.md`` + ``baseline_config.json``)."""
    path = Path(task_dir)
    prompt_path = path / "prompt.md"
    config_path = path / "baseline_config.json"
    if not prompt_path.exists() or not config_path.exists():
        raise FileNotFoundError(
            f"Training task dir {path} must contain prompt.md and baseline_config.json."
        )
    baseline = TrainConfig.model_validate_json(config_path.read_text(encoding="utf-8"))
    return LoadedTrainingTask(
        task_id=path.name,
        path=str(path),
        prompt=prompt_path.read_text(encoding="utf-8"),
        baseline_config=baseline,
    )


def _read_lines(path: Path) -> Iterator[str]:
    if not path.exists():
        return iter(())
    with path.open("r", encoding="utf-8") as fh:
        return iter([line for line in (raw.strip() for raw in fh) if line])


class TrainingArchive:
    """Append-only JSONL archive of :class:`TrainingAttempt`s — separate from code attempts.

    Kept in its own file (``runs/training_attempts.jsonl``) so a training attempt is never
    confused with a code attempt, and every config delta tried — promoted or rejected —
    stays auditable (Goal 06: "Candidate changes are logged as diffs or config deltas").
    """

    def __init__(self, path: str | Path = DEFAULT_TRAINING_ATTEMPTS_PATH) -> None:
        self.path = Path(path)

    def append(self, attempt: TrainingAttempt) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(attempt.model_dump_json() + "\n")

    def read_all(self) -> list[TrainingAttempt]:
        return [TrainingAttempt.model_validate_json(line) for line in _read_lines(self.path)]

    def __len__(self) -> int:
        return sum(1 for _ in _read_lines(self.path))


def select_best_training(attempts: list[TrainingAttempt]) -> TrainingAttempt | None:
    """Return the attempt with the lowest reproducible validation loss, or ``None``.

    Attempts without a reproducible result (out-of-bounds, timeouts, errors) are ignored
    for selection but remain in the archive as negative results.
    """
    scored = [a for a in attempts if a.result is not None and a.result.reproducible]
    if not scored:
        return None
    return min(scored, key=lambda a: a.result.val_loss)


# --------------------------------------------------------------------------- #
# The training inner loop.
# --------------------------------------------------------------------------- #


def config_delta_str(base: TrainConfig, candidate: TrainConfig) -> str:
    """A compact human-readable diff of changed hyperparameters (logged on each attempt)."""
    changes = [
        f"{name}: {getattr(base, name)} → {getattr(candidate, name)}"
        for name in TrainConfig.model_fields
        if getattr(base, name) != getattr(candidate, name)
    ]
    return "; ".join(changes) if changes else "(no change from parent)"


@dataclass
class TrainingRunResult:
    """Outcome of one :meth:`TrainingController.run_training` invocation."""

    task_id: str
    attempts: list[TrainingAttempt] = field(default_factory=list)
    best: TrainingAttempt | None = None


def _short_id() -> str:
    return uuid.uuid4().hex[:12]


class TrainingController:
    """Drives the per-task training improvement loop under a fixed wall-clock budget."""

    def __init__(
        self,
        archive: TrainingArchive | None = None,
        sandbox: Sandbox | None = None,
        ledger=None,  # noqa: ANN001 - ModelCallLedger, kept loose to avoid a hard import cycle
        budget_seconds: float = DEFAULT_BUDGET_SECONDS,
        budget=None,  # noqa: ANN001 - BudgetTracker; None = unbounded (Tier 0 default)
    ) -> None:
        self.archive = TrainingArchive() if archive is None else archive
        self.sandbox = Sandbox() if sandbox is None else sandbox
        self.ledger = ledger
        self.budget_seconds = budget_seconds
        # Token/USD ceilings (Goal 07); None = unbounded, the Tier 0 default.
        self.budget = budget

    def _evaluate(self, config: TrainConfig) -> tuple[TrainResult, GateResult]:
        """Bounds-check a config, then (only if in bounds) train it under the budget."""
        bounds = config_bounds_gate(config)
        if bounds.decision is not GateDecision.PASSED:
            # Out of bounds: never executed. A negative result with no run.
            return (
                TrainResult(reproducible=False, error="config out of bounds"),
                bounds,
            )
        run = self.sandbox.run_training(config.model_dump(), self.budget_seconds)
        return to_result(run), bounds

    def _attempt(
        self, config: TrainConfig, task_id: str, parent_id: str | None
    ) -> TrainingAttempt:
        result, bounds = self._evaluate(config)
        if bounds.decision is not GateDecision.PASSED:
            reason = bounds.findings[0] if bounds.findings else "config out of bounds"
        elif result.timed_out:
            reason = "training timed out (budget exceeded)"
        elif not result.reproducible:
            reason = result.error or "no validation metric"
        else:
            reason = f"val_loss={result.val_loss:.6f}"
        return TrainingAttempt(
            attempt_id=_short_id(),
            task_id=task_id,
            config=config,
            parent_id=parent_id,
            result=result,
            status=AttemptStatus.REJECTED,  # finalized by the caller
            reason=reason,
            gates=GateReport(results=[bounds]),
        )

    def _log_model_call(self, model: ModelClient, prompt: str, latency_ms: float, task_id: str) -> None:
        # Capture per-call usage (tokens/cost) for the audit ledger and charge the
        # budget — every model call is logged even the one that trips a ceiling (Goal 07).
        usage = getattr(model, "last_usage", None)
        if self.ledger is not None:
            import hashlib

            self.ledger.append(
                ModelCall(
                    provider=getattr(model, "provider", "unknown"),
                    model=getattr(model, "model", "unknown"),
                    prompt_hash=hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16],
                    input_tokens=usage.input_tokens if usage else 0,
                    output_tokens=usage.output_tokens if usage else 0,
                    cost_usd=usage.cost_usd if usage else 0.0,
                    latency_ms=(usage.latency_ms if usage and usage.latency_ms else latency_ms),
                    pricing_metadata=usage.pricing_metadata if usage else {},
                    experiment_id=task_id,
                )
            )
        if self.budget is not None and usage is not None:
            self.budget.charge(usage)

    def _build_prompt(self, task: LoadedTrainingTask, current: TrainConfig) -> str:
        from .prompts import load_prompt

        template = load_prompt("training_improver")
        bounds_lines = "\n".join(
            f"- {name}: [{lo}, {hi}]" for name, (lo, hi) in TRAIN_BOUNDS.items()
        )
        bounds_lines += f"\n- lr_schedule: one of {sorted(LR_SCHEDULES)}"
        return (
            template.replace("{task_prompt}", task.prompt)
            .replace("{budget_seconds}", str(self.budget_seconds))
            .replace("{current_config}", current.model_dump_json(indent=2))
            .replace("{bounds}", bounds_lines)
        )

    def run_training(
        self,
        task_dir: str | Path,
        model: ModelClient,
        generations: int = 5,
    ) -> TrainingRunResult:
        """Run the training improvement loop for a task directory.

        Generation 0 trains the fixed baseline config (the metric to beat); each
        subsequent generation asks ``model`` for a bounded config delta, trains it under
        the fixed budget, archives the attempt (in bounds *or* not, passing *or* failing),
        and keeps the lowest reproducible validation loss as the seed for the next
        generation. A new best must beat the incumbent by ``MIN_VAL_LOSS_IMPROVEMENT`` and
        clear the reproducibility gate before it is promoted.
        """
        task = load_training_task(task_dir)
        result = TrainingRunResult(task_id=task.task_id)

        baseline = self._attempt(task.baseline_config, task.task_id, parent_id=None)
        baseline.status = (
            AttemptStatus.PROMOTED if baseline.result.reproducible else AttemptStatus.ERROR
        )
        self.archive.append(baseline)
        result.attempts.append(baseline)
        best = baseline

        for _ in range(generations):
            prompt = self._build_prompt(task, best.config)
            start = time.perf_counter()
            raw = model.generate(prompt)
            latency_ms = (time.perf_counter() - start) * 1000.0
            self._log_model_call(model, prompt, latency_ms, task.task_id)

            candidate_config = apply_delta(best.config, extract_config_delta(raw))
            attempt = self._attempt(candidate_config, task.task_id, parent_id=best.attempt_id)
            attempt.reason = (
                f"{config_delta_str(best.config, candidate_config)} | {attempt.reason}"
            )

            if attempt.gates.failed:
                attempt.status = AttemptStatus.REJECTED
            elif not attempt.result.reproducible:
                attempt.status = AttemptStatus.ERROR if not attempt.result.timed_out else AttemptStatus.REJECTED
            elif attempt.result.val_loss < best.result.val_loss - MIN_VAL_LOSS_IMPROVEMENT:
                gate = training_reproducibility_gate(candidate_config, self.sandbox, self.budget_seconds)
                attempt.gates = GateReport(results=[*attempt.gates.results, gate])
                if gate.decision is GateDecision.PASSED:
                    attempt.status = AttemptStatus.PROMOTED
                    best = attempt
                else:
                    attempt.status = AttemptStatus.REJECTED
                    attempt.reason = f"{attempt.reason} | {gate.findings[0] if gate.findings else 'not reproducible'}"
            else:
                attempt.status = AttemptStatus.REJECTED

            self.archive.append(attempt)
            result.attempts.append(attempt)

        result.best = best
        return result


__all__ = [
    "DEFAULT_TRAINING_ATTEMPTS_PATH",
    "DEFAULT_BUDGET_SECONDS",
    "TRAIN_BOUNDS",
    "LR_SCHEDULES",
    "MIN_VAL_LOSS_IMPROVEMENT",
    "config_bounds",
    "config_bounds_gate",
    "extract_config_delta",
    "apply_delta",
    "to_result",
    "training_reproducibility_gate",
    "LoadedTrainingTask",
    "load_training_task",
    "TrainingArchive",
    "select_best_training",
    "config_delta_str",
    "TrainingRunResult",
    "TrainingController",
]
