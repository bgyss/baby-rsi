"""EDA evaluator adapter for the chip-design pack (Goal 25).

Each chip task ships its own controller-owned ``eval.py`` that drives an offline Yosys flow:
a formal-equivalence check against a controller-owned reference (correctness, a hard
precondition) followed by a synthesis pass that reports PPA (area). The adapter is the
default ``EvalPyAdapter`` bound to the pack's declared regime (``statistical``), so the Goal
24 confidence-bound gate governs PPA promotion — equivalence still gates any PPA credit.
"""

from siro.packs import EvalPyAdapter, EvaluatorRegime


def get_adapter(regime: EvaluatorRegime) -> EvalPyAdapter:
    """Run each chip task's controller-owned eval.py under the pack's statistical regime."""
    return EvalPyAdapter(regime=regime)
