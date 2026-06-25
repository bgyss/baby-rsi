"""The *fixed* tiny-training benchmark (Goal 06) — the training analogue of a task's
test suite.

This module is the controller-owned, candidate-immutable part of a training
experiment: a deterministic dataset, a fixed model architecture family, a fixed loss,
and a fixed validation metric. A *candidate* never edits this file — it only proposes a
bounded :class:`~siro.schemas.TrainConfig` (hyperparameters). That asymmetry is exactly
how the Goal 06 constraints are enforced *structurally*:

- the **validation data** is built from a fixed ``DATA_SEED`` that is not part of any
  config, so a candidate cannot change what it is evaluated on;
- the **metric** (mean validation cross-entropy) is defined only here;
- the **wall-clock budget** is passed in by the controller, not by the candidate, and
  is honored cooperatively (training stops when the budget elapses) *and* enforced
  hard by the sandbox subprocess timeout.

The implementation is pure standard library (a tiny 2-layer MLP trained by minibatch
SGD) so Tier 0 stays fully local and offline with no extra dependencies and no
autonomous package install. It is importable (``train``) for in-process determinism
checks and runnable as a script (``python training_task.py config.json``) so the
sandbox can execute it in isolation, reading a config JSON and printing a result JSON.
"""

from __future__ import annotations

import json
import math
import random
import sys
import time

# --------------------------------------------------------------------------- #
# Fixed, candidate-immutable benchmark definition.
# --------------------------------------------------------------------------- #

#: Seed for the *validation/training data*. It lives here, never in TrainConfig, so a
#: candidate cannot cause a metric change by altering the data it is scored on
#: (Goal 06 acceptance: "Metric changes cannot be caused by changed validation data").
DATA_SEED = 1234
#: A three-class 2-D classification problem. Small enough to train many times within a
#: few seconds, large enough that hyperparameters genuinely matter.
N_CLASSES = 3
N_FEATURES = 2
N_PER_CLASS = 100
#: Fixed train/val split: the first ``TRAIN_PER_CLASS`` points of each class train, the
#: rest validate. Fixed indices ⇒ the validation set is identical across all candidates.
TRAIN_PER_CLASS = 70
#: Cluster geometry (fixed): class centers on a circle, with fixed Gaussian noise.
CENTER_RADIUS = 2.5
NOISE_STD = 0.75


def make_dataset() -> tuple[list[list[float]], list[int], list[list[float]], list[int]]:
    """Build the fixed (train_x, train_y, val_x, val_y) split deterministically.

    Depends only on the module-level fixed constants — never on a candidate config — so
    every candidate is trained and scored on exactly the same data.
    """
    rng = random.Random(DATA_SEED)
    centers = [
        (
            CENTER_RADIUS * math.cos(2 * math.pi * c / N_CLASSES),
            CENTER_RADIUS * math.sin(2 * math.pi * c / N_CLASSES),
        )
        for c in range(N_CLASSES)
    ]
    train_x: list[list[float]] = []
    train_y: list[int] = []
    val_x: list[list[float]] = []
    val_y: list[int] = []
    for c in range(N_CLASSES):
        cx, cy = centers[c]
        for i in range(N_PER_CLASS):
            point = [cx + rng.gauss(0.0, NOISE_STD), cy + rng.gauss(0.0, NOISE_STD)]
            if i < TRAIN_PER_CLASS:
                train_x.append(point)
                train_y.append(c)
            else:
                val_x.append(point)
                val_y.append(c)
    return train_x, train_y, val_x, val_y


# --------------------------------------------------------------------------- #
# A tiny 2-layer MLP (pure Python), softmax + cross-entropy.
# --------------------------------------------------------------------------- #


def _softmax(logits: list[float]) -> list[float]:
    m = max(logits)
    exps = [math.exp(z - m) for z in logits]
    s = sum(exps)
    return [e / s for e in exps]


def _init_weights(rng: random.Random, n_in: int, n_out: int) -> list[list[float]]:
    """Small uniform init scaled by fan-in (deterministic given ``rng``)."""
    scale = 1.0 / math.sqrt(n_in)
    return [[rng.uniform(-scale, scale) for _ in range(n_in)] for _ in range(n_out)]


def _lr_at(base_lr: float, schedule: str, epoch: int, epochs: int) -> float:
    """Learning rate for ``epoch`` under the chosen schedule (fixed schedule family)."""
    if schedule == "step":
        step = max(epochs // 3, 1)
        return base_lr * (0.5 ** (epoch // step))
    if schedule == "cosine":
        return base_lr * 0.5 * (1.0 + math.cos(math.pi * epoch / max(epochs, 1)))
    return base_lr  # "constant"


def _forward(
    x: list[float],
    w1: list[list[float]],
    b1: list[float],
    w2: list[list[float]],
    b2: list[float],
) -> tuple[list[float], list[float]]:
    """Return (hidden activations, class probabilities) for one input."""
    h = [
        math.tanh(sum(w1[j][k] * x[k] for k in range(len(x))) + b1[j])
        for j in range(len(w1))
    ]
    logits = [
        sum(w2[i][j] * h[j] for j in range(len(h))) + b2[i] for i in range(len(w2))
    ]
    return h, _softmax(logits)


def _mean_cross_entropy(
    xs: list[list[float]],
    ys: list[int],
    w1: list[list[float]],
    b1: list[float],
    w2: list[list[float]],
    b2: list[float],
) -> float:
    """Mean cross-entropy (nats) over a dataset — the fixed validation metric."""
    total = 0.0
    for x, y in zip(xs, ys):
        _, probs = _forward(x, w1, b1, w2, b2)
        total += -math.log(max(probs[y], 1e-12))
    return total / len(xs)


def train(config: dict, budget_seconds: float = 10.0) -> dict:
    """Train under ``config`` within ``budget_seconds`` and return a result dict.

    The result carries the fixed validation metric (``val_loss`` = mean validation
    cross-entropy), the final ``train_loss``, ``throughput`` (samples/sec), and bookkeeping
    (epochs completed, steps, wall-clock, whether the budget stopped it early). Lower
    ``val_loss`` is better; it is computed only on the fixed validation split.
    """
    lr = float(config["learning_rate"])
    schedule = str(config["lr_schedule"])
    batch_size = int(config["batch_size"])
    hidden = int(config["hidden_size"])
    momentum = float(config["momentum"])
    weight_decay = float(config["weight_decay"])
    epochs = int(config["epochs"])
    init_seed = int(config["init_seed"])

    train_x, train_y, val_x, val_y = make_dataset()
    n = len(train_x)

    init_rng = random.Random(init_seed)
    w1 = _init_weights(init_rng, N_FEATURES, hidden)
    b1 = [0.0] * hidden
    w2 = _init_weights(init_rng, hidden, N_CLASSES)
    b2 = [0.0] * N_CLASSES
    # Momentum velocity buffers (same shapes as the parameters).
    vw1 = [[0.0] * N_FEATURES for _ in range(hidden)]
    vb1 = [0.0] * hidden
    vw2 = [[0.0] * hidden for _ in range(N_CLASSES)]
    vb2 = [0.0] * N_CLASSES

    order_rng = random.Random(init_seed + 1)  # deterministic minibatch shuffling
    start = time.perf_counter()
    samples_processed = 0
    steps = 0
    epochs_completed = 0
    budget_hit = False

    for epoch in range(epochs):
        if time.perf_counter() - start >= budget_seconds:
            budget_hit = True
            break
        epoch_lr = _lr_at(lr, schedule, epoch, epochs)
        indices = list(range(n))
        order_rng.shuffle(indices)
        for batch_start in range(0, n, batch_size):
            batch = indices[batch_start : batch_start + batch_size]
            # Accumulate gradients over the minibatch.
            gw1 = [[0.0] * N_FEATURES for _ in range(hidden)]
            gb1 = [0.0] * hidden
            gw2 = [[0.0] * hidden for _ in range(N_CLASSES)]
            gb2 = [0.0] * N_CLASSES
            for idx in batch:
                x = train_x[idx]
                y = train_y[idx]
                h, probs = _forward(x, w1, b1, w2, b2)
                # dL/dlogits = probs - onehot(y)
                dlogits = list(probs)
                dlogits[y] -= 1.0
                for i in range(N_CLASSES):
                    for j in range(hidden):
                        gw2[i][j] += dlogits[i] * h[j]
                    gb2[i] += dlogits[i]
                # backprop into hidden (tanh': 1 - h^2)
                dh = [
                    (1.0 - h[j] * h[j])
                    * sum(w2[i][j] * dlogits[i] for i in range(N_CLASSES))
                    for j in range(hidden)
                ]
                for j in range(hidden):
                    for k in range(N_FEATURES):
                        gw1[j][k] += dh[j] * x[k]
                    gb1[j] += dh[j]
            scale = 1.0 / len(batch)
            # SGD with momentum + L2 weight decay.
            for i in range(N_CLASSES):
                for j in range(hidden):
                    grad = gw2[i][j] * scale + weight_decay * w2[i][j]
                    vw2[i][j] = momentum * vw2[i][j] - epoch_lr * grad
                    w2[i][j] += vw2[i][j]
                vb2[i] = momentum * vb2[i] - epoch_lr * (gb2[i] * scale)
                b2[i] += vb2[i]
            for j in range(hidden):
                for k in range(N_FEATURES):
                    grad = gw1[j][k] * scale + weight_decay * w1[j][k]
                    vw1[j][k] = momentum * vw1[j][k] - epoch_lr * grad
                    w1[j][k] += vw1[j][k]
                vb1[j] = momentum * vb1[j] - epoch_lr * (gb1[j] * scale)
                b1[j] += vb1[j]
            samples_processed += len(batch)
            steps += 1
        epochs_completed += 1

    wall_clock_ms = (time.perf_counter() - start) * 1000.0
    val_loss = _mean_cross_entropy(val_x, val_y, w1, b1, w2, b2)
    train_loss = _mean_cross_entropy(train_x, train_y, w1, b1, w2, b2)
    throughput = samples_processed / max(wall_clock_ms / 1000.0, 1e-9)
    return {
        "val_loss": val_loss,
        "train_loss": train_loss,
        "throughput": throughput,
        "steps": steps,
        "epochs_completed": epochs_completed,
        "wall_clock_ms": wall_clock_ms,
        "budget_hit": budget_hit,
        "n_val": len(val_x),
    }


def _main(argv: list[str]) -> int:
    """Script entrypoint: ``python training_task.py <config.json>`` → result JSON on stdout.

    The config JSON carries the candidate hyperparameters plus a controller-injected
    ``_budget_seconds`` (the fixed wall-clock budget — never a candidate-tunable field).
    """
    if len(argv) < 2:
        print(json.dumps({"error": "usage: training_task.py <config.json>"}))
        return 2
    with open(argv[1], encoding="utf-8") as fh:
        config = json.load(fh)
    budget_seconds = float(config.get("_budget_seconds", 10.0))
    result = train(config, budget_seconds=budget_seconds)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via the sandbox subprocess
    raise SystemExit(_main(sys.argv))
