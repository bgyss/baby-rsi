# Research task — `tiny_mlp` (Karpathy-style tiny training)

## Objective

Lower the **validation loss** of a tiny 2-layer MLP on a fixed, deterministic 2-class
problem by tuning the hyperparameters in `config.py`, **within a fixed wall-clock budget**.

## Success metric

- **Primary:** `val_loss` — mean cross-entropy on a held-out validation split (lower is
  better). The split and model are fixed and controller-owned; you only change the config.
- **Precondition (`passed`):** training must finish all epochs **within the wall-clock
  budget** and produce a finite loss. A config so expensive it is cut off by the budget
  does not pass — keep it inside the budget.

## Allowed edit surface

`config.py` only. It must define a dict named `CONFIG` with these keys (and only these):

- `learning_rate` (float), `epochs` (int), `hidden_size` (int), `batch_size` (int),
  `seed` (int).

The dataset, model architecture, loss, validation split, and wall-clock budget are
**fixed** by the evaluator and are not tunable — so a lower loss reflects genuinely better
training, never changed validation data.

## Constraints

- Pure standard-library Python. No file/network/subprocess access in the candidate.
- The evaluator (`eval.py`) is read-only to you; promotion is decided by it, reproducibly.
