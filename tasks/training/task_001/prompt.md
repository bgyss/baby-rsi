# Training Task 001 — tiny MLP classifier

Improve the training of a tiny 2-layer MLP on a fixed, deterministic three-class 2-D
classification problem. The objective is to **minimize the validation loss** (mean
validation cross-entropy) reachable within the fixed wall-clock budget.

The model, dataset, train/validation split, loss, and metric are all fixed by the
benchmark (`src/siro/training_task.py`) and are **not** editable. The baseline
configuration in `baseline_config.json` uses a deliberately conservative learning
rate, so there is real headroom to improve by tuning the optimizer.

You may propose constrained changes only to the hyperparameters (learning-rate value
and schedule, batch size, hidden size, momentum, weight decay, epochs, init seed),
each within its allowed bounds. You may not change the validation data, the metric,
the budget, or the dataset; you may not disable evaluation, download data, or install
packages.

## Reproducibility metadata

- Data seed: `DATA_SEED = 1234` (fixed; never part of any config).
- Dataset: 3 classes × 100 points (2-D Gaussian clusters); first 70 of each class are
  training, the rest are validation (210 train / 90 validation, fixed indices).
- Metric: mean validation cross-entropy in nats (lower is better). Secondary:
  training throughput (samples/sec).
- Training is fully deterministic given a config, so a baseline or candidate run
  reproduces its validation loss exactly across reruns.
