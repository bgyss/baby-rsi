"""Objective, reproducible evaluator for the `tiny_mlp` research task (Goal 09).

Controller-owned: copied into the offline sandbox, never candidate-supplied. It defines
the **fixed** benchmark — a deterministic 2-class dataset, a fixed 2-layer MLP, the
cross-entropy loss, and the validation split — and trains under the candidate's `CONFIG`
within the controller-injected wall-clock budget (read from `_budget.json`). A candidate
can only change hyperparameters in `config.py`; it cannot change the data it is scored on,
so a lower `val_loss` reflects genuinely better training (no validation-data tampering).

Deterministic by construction (fixed data seed, fixed init given the config seed), so the
reproducibility gate's rerun sees an identical `val_loss`. Prints one JSON metric record.
"""

from __future__ import annotations

import json
import math
import random
import time
from pathlib import Path

# --- fixed, candidate-immutable benchmark ----------------------------------- #
DATA_SEED = 4321
N_FEATURES = 2
N_CLASSES = 2
N_PER_CLASS = 60
TRAIN_PER_CLASS = 40
CENTER_RADIUS = 2.0
NOISE_STD = 0.8


def make_dataset():
    rng = random.Random(DATA_SEED)
    centers = [
        (CENTER_RADIUS * math.cos(math.pi * c), CENTER_RADIUS * math.sin(math.pi * c))
        for c in range(N_CLASSES)
    ]
    tr_x, tr_y, va_x, va_y = [], [], [], []
    for c in range(N_CLASSES):
        cx, cy = centers[c]
        for i in range(N_PER_CLASS):
            point = [cx + rng.gauss(0.0, NOISE_STD), cy + rng.gauss(0.0, NOISE_STD)]
            (tr_x if i < TRAIN_PER_CLASS else va_x).append(point)
            (tr_y if i < TRAIN_PER_CLASS else va_y).append(c)
    return tr_x, tr_y, va_x, va_y


def _softmax(logits):
    m = max(logits)
    exps = [math.exp(z - m) for z in logits]
    s = sum(exps)
    return [e / s for e in exps]


def _forward(x, w1, b1, w2, b2):
    h = [math.tanh(sum(w1[j][k] * x[k] for k in range(len(x))) + b1[j]) for j in range(len(w1))]
    logits = [sum(w2[i][j] * h[j] for j in range(len(h))) + b2[i] for i in range(len(w2))]
    return h, _softmax(logits)


def _mean_ce(xs, ys, w1, b1, w2, b2):
    total = 0.0
    for x, y in zip(xs, ys):
        _, probs = _forward(x, w1, b1, w2, b2)
        total += -math.log(max(probs[y], 1e-12))
    return total / len(xs)


def train(config, budget_seconds):
    lr = float(config["learning_rate"])
    epochs = int(config["epochs"])
    hidden = int(config["hidden_size"])
    batch_size = max(int(config["batch_size"]), 1)
    seed = int(config["seed"])

    tr_x, tr_y, va_x, va_y = make_dataset()
    n = len(tr_x)
    init = random.Random(seed)
    scale = 1.0 / math.sqrt(N_FEATURES)
    w1 = [[init.uniform(-scale, scale) for _ in range(N_FEATURES)] for _ in range(hidden)]
    b1 = [0.0] * hidden
    w2 = [[init.uniform(-scale, scale) for _ in range(hidden)] for _ in range(N_CLASSES)]
    b2 = [0.0] * N_CLASSES

    order = random.Random(seed + 1)
    start = time.perf_counter()
    budget_hit = False
    for _ in range(epochs):
        if time.perf_counter() - start >= budget_seconds:
            budget_hit = True
            break
        idx = list(range(n))
        order.shuffle(idx)
        for bs in range(0, n, batch_size):
            batch = idx[bs : bs + batch_size]
            gw1 = [[0.0] * N_FEATURES for _ in range(hidden)]
            gb1 = [0.0] * hidden
            gw2 = [[0.0] * hidden for _ in range(N_CLASSES)]
            gb2 = [0.0] * N_CLASSES
            for i in batch:
                x, y = tr_x[i], tr_y[i]
                h, probs = _forward(x, w1, b1, w2, b2)
                dlog = list(probs)
                dlog[y] -= 1.0
                for a in range(N_CLASSES):
                    for j in range(hidden):
                        gw2[a][j] += dlog[a] * h[j]
                    gb2[a] += dlog[a]
                dh = [
                    (1.0 - h[j] * h[j]) * sum(w2[a][j] * dlog[a] for a in range(N_CLASSES))
                    for j in range(hidden)
                ]
                for j in range(hidden):
                    for k in range(N_FEATURES):
                        gw1[j][k] += dh[j] * x[k]
                    gb1[j] += dh[j]
            inv = 1.0 / len(batch)
            for a in range(N_CLASSES):
                for j in range(hidden):
                    w2[a][j] -= lr * gw2[a][j] * inv
                b2[a] -= lr * gb2[a] * inv
            for j in range(hidden):
                for k in range(N_FEATURES):
                    w1[j][k] -= lr * gw1[j][k] * inv
                b1[j] -= lr * gb1[j] * inv

    val_loss = _mean_ce(va_x, va_y, w1, b1, w2, b2)
    train_loss = _mean_ce(tr_x, tr_y, w1, b1, w2, b2)
    return val_loss, train_loss, budget_hit


def main() -> int:
    try:
        import config as cfg  # noqa: PLC0415 - candidate edit surface
        conf = cfg.CONFIG
    except Exception as exc:  # pragma: no cover
        print(json.dumps({"error": f"could not load config.py: {exc}"}))
        return 0

    budget = 8.0
    budget_path = Path("_budget.json")
    if budget_path.exists():
        budget = float(json.loads(budget_path.read_text(encoding="utf-8")).get("budget_seconds", budget))

    try:
        val_loss, train_loss, budget_hit = train(conf, budget)
    except Exception as exc:
        print(json.dumps({"primary": 0.0, "passed": False, "notes": f"training raised: {exc}"}))
        return 0

    finite = math.isfinite(val_loss)
    passed = finite and not budget_hit
    print(
        json.dumps(
            {
                "primary": round(val_loss, 9) if finite else 1e9,
                "passed": passed,
                "secondary": {"train_loss": round(train_loss, 9) if math.isfinite(train_loss) else 1e9},
                "notes": "budget_hit" if budget_hit else "completed within budget",
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
