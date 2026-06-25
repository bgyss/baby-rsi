"""Tiny-training autoresearch loop (Goal 06), fully offline.

Covers the acceptance criteria: a reproducible baseline, candidates limited to a fixed
budget, config deltas logged, a best candidate that beats the baseline reproducibly, and
the structural guarantee that the validation data/metric/budget cannot be changed by a
candidate.
"""

import json

from siro.model_client import ScriptedModelClient
from siro.sandbox import Sandbox
from siro.schemas import AttemptStatus, TrainConfig
from siro.training import (
    LR_SCHEDULES,
    TRAIN_BOUNDS,
    TrainingArchive,
    TrainingController,
    apply_delta,
    config_bounds,
    config_bounds_gate,
    extract_config_delta,
    load_training_task,
    select_best_training,
    to_result,
)
from siro.training_task import make_dataset, train

TASK_DIR = "tasks/training/task_001"
# A short budget keeps the suite fast; the tiny model trains in well under a second.
BUDGET = 5.0


def _delta(**kwargs) -> str:
    return f"```json\n{json.dumps(kwargs)}\n```"


# --------------------------------------------------------------------------- #
# Fixed benchmark: determinism + immutable validation data.
# --------------------------------------------------------------------------- #


def test_dataset_is_fixed_and_independent_of_config():
    # The validation split is built from the fixed DATA_SEED, never from a config, so it
    # is identical regardless of any hyperparameters — metric changes cannot come from
    # changed validation data.
    a = make_dataset()
    b = make_dataset()
    assert a == b
    _, _, val_x, val_y = a
    assert len(val_x) == 90 and len(val_y) == 90


def test_training_is_reproducible():
    cfg = TrainConfig().model_dump()
    r1 = train(cfg, budget_seconds=BUDGET)
    r2 = train(cfg, budget_seconds=BUDGET)
    assert r1["val_loss"] == r2["val_loss"]


def test_config_has_no_data_or_metric_or_budget_field():
    # The edit surface cannot even *represent* changing the data, metric, or budget.
    fields = set(TrainConfig.model_fields)
    for forbidden in ("data", "dataset", "val", "validation", "metric", "budget", "seconds"):
        assert not any(forbidden in f for f in fields), f"edit surface exposes '{forbidden}'"


# --------------------------------------------------------------------------- #
# Bounds (the training "safety gate").
# --------------------------------------------------------------------------- #


def test_in_bounds_config_passes():
    ok, findings = config_bounds(TrainConfig())
    assert ok and findings == []
    assert config_bounds_gate(TrainConfig()).decision.value == "passed"


def test_out_of_bounds_config_is_rejected():
    cfg = TrainConfig(hidden_size=9999)
    ok, findings = config_bounds(cfg)
    assert not ok and any("hidden_size" in f for f in findings)
    assert config_bounds_gate(cfg).decision.value == "failed"


def test_unknown_schedule_is_rejected():
    cfg = TrainConfig.model_construct(**{**TrainConfig().model_dump(), "lr_schedule": "magic"})
    ok, findings = config_bounds(cfg)
    assert not ok and any("lr_schedule" in f for f in findings)
    assert "constant" in LR_SCHEDULES and "cosine" in LR_SCHEDULES


def test_bounds_cover_every_tunable_field():
    numeric_fields = {
        f for f in TrainConfig.model_fields if f not in {"lr_schedule", "init_seed"}
    }
    assert numeric_fields == set(TRAIN_BOUNDS)


# --------------------------------------------------------------------------- #
# Delta parsing: only known fields, never a smuggled budget/data override.
# --------------------------------------------------------------------------- #


def test_extract_config_delta_from_fenced_json():
    assert extract_config_delta(_delta(learning_rate=0.2)) == {"learning_rate": 0.2}


def test_apply_delta_ignores_unknown_keys():
    base = TrainConfig()
    updated = apply_delta(base, {"learning_rate": 0.5, "_budget_seconds": 999, "data": "evil"})
    assert updated.learning_rate == 0.5
    # The smuggled budget/data keys are dropped — the edit surface is the schema's fields.
    assert not hasattr(updated, "_budget_seconds")
    assert updated.batch_size == base.batch_size


# --------------------------------------------------------------------------- #
# The loop: baseline + budget + logged deltas + reproducible improvement.
# --------------------------------------------------------------------------- #


def test_load_training_task_reads_fixture():
    task = load_training_task(TASK_DIR)
    assert task.task_id == "task_001"
    assert task.baseline_config.learning_rate == 0.02


def test_baseline_runs_and_is_promoted(tmp_path):
    archive = TrainingArchive(tmp_path / "t.jsonl")
    controller = TrainingController(archive=archive, budget_seconds=BUDGET)
    # No improving proposals: every generation reverts to the baseline LR (no gain).
    model = ScriptedModelClient([_delta(learning_rate=0.02)])
    result = controller.run_training(TASK_DIR, model=model, generations=2)
    baseline = result.attempts[0]
    assert baseline.status is AttemptStatus.PROMOTED
    assert baseline.result is not None and baseline.result.reproducible
    assert result.best.attempt_id == baseline.attempt_id


def test_best_candidate_beats_baseline_reproducibly(tmp_path):
    archive = TrainingArchive(tmp_path / "t.jsonl")
    controller = TrainingController(archive=archive, budget_seconds=BUDGET)
    model = ScriptedModelClient([_delta(learning_rate=0.3, momentum=0.9, hidden_size=16)])
    result = controller.run_training(TASK_DIR, model=model, generations=3)

    baseline = result.attempts[0]
    assert result.best.attempt_id != baseline.attempt_id
    assert result.best.status is AttemptStatus.PROMOTED
    # The promoted candidate strictly improved validation loss...
    assert result.best.result.val_loss < baseline.result.val_loss
    # ...and cleared the reproducibility gate.
    gate_names = {r.gate for r in result.best.gates.results}
    assert "training_reproducibility" in gate_names


def test_every_attempt_is_archived_including_negatives(tmp_path):
    archive = TrainingArchive(tmp_path / "t.jsonl")
    controller = TrainingController(archive=archive, budget_seconds=BUDGET)
    model = ScriptedModelClient(
        [
            _delta(learning_rate=0.3, momentum=0.9),  # improves
            _delta(hidden_size=9999),  # out of bounds → negative result, archived
        ]
    )
    result = controller.run_training(TASK_DIR, model=model, generations=2)
    archived = archive.read_all()
    assert len(archived) == 3  # baseline + 2 generations, all recorded
    assert len(result.attempts) == 3
    # The out-of-bounds attempt is kept as a rejected negative result.
    oob = result.attempts[-1]
    assert oob.status is AttemptStatus.REJECTED
    assert "out of bounds" in oob.reason
    assert select_best_training(archived).result.reproducible


def test_config_delta_is_logged(tmp_path):
    archive = TrainingArchive(tmp_path / "t.jsonl")
    controller = TrainingController(archive=archive, budget_seconds=BUDGET)
    model = ScriptedModelClient([_delta(learning_rate=0.25)])
    controller.run_training(TASK_DIR, model=model, generations=1)
    gen1 = archive.read_all()[1]
    assert "learning_rate" in gen1.reason and "0.02" in gen1.reason and "0.25" in gen1.reason


def test_candidate_limited_to_budget(tmp_path):
    # The sandbox enforces the wall-clock budget: a config that asks for far more epochs
    # than fit in the budget stops at the budget, and the run stays near it.
    sandbox = Sandbox()
    run = sandbox.run_training(TrainConfig(epochs=200).model_dump(), budget_seconds=1.0)
    result = to_result(run)
    assert result.reproducible
    # Cooperative budget stop (or finished early); never far past the hard ceiling.
    assert result.wall_clock_ms <= 1000.0 + 5000.0
