# Goal Prompt 06 — Local Training Autoresearch

## Goal

Extend the testbed from code-task improvement to a small Karpathy-style local training experiment loop.

## Objective

Allow agents to propose constrained edits to a tiny model training configuration or training script and evaluate them under a fixed wall-clock budget.

## Requirements

Create a tiny training benchmark with:

- Fixed dataset preparation
- Fixed evaluation metric
- Fixed wall-clock budget
- Baseline training script
- Candidate edit surface
- Reproducibility metadata

Candidate changes may include:

- Learning-rate schedule
- Batch size within bounds
- Optimizer hyperparameters
- Small architecture parameters within bounds
- Regularization settings

Candidate changes may not include:

- Changing validation data
- Changing metric definition
- Disabling evaluation
- Expanding runtime budget
- Downloading new datasets
- Installing packages autonomously

## Metrics

Use a primary metric that is stable across candidate variants, such as:

- validation loss under fixed data/tokenization
- validation bits-per-byte if tokenizer changes are permitted
- training throughput as a secondary metric

## Acceptance criteria

- Baseline run is reproducible.
- Candidate runs are limited to a fixed time budget.
- Candidate changes are logged as diffs or config deltas.
- Best candidate must beat baseline reproducibly.
- Metric changes cannot be caused by changed validation data.

## Safety constraints

- Run locally only.
- No cloud compute.
- No model deployment.
- No autonomous fine-tuning of large models.
- Human review required before expanding benchmark scope.
