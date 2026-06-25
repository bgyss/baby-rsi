"""Seed training config for the `tiny_mlp` research task (deliberately under-tuned).

The learning rate is tiny and there are too few epochs, so the model barely moves off its
initialization and validation loss is high. The research org tunes these — within the
fixed wall-clock budget — to lower held-out validation loss.
"""

CONFIG = {
    "learning_rate": 0.01,
    "epochs": 8,
    "hidden_size": 4,
    "batch_size": 16,
    "seed": 0,
}
