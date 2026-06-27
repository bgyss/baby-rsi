"""Lean proof-checking evaluator for the math pack."""

from siro.packs import EvalPyAdapter, EvaluatorRegime


def get_adapter(regime: EvaluatorRegime) -> EvalPyAdapter:
    """Run each math task's controller-owned eval.py under the exact regime."""
    return EvalPyAdapter(regime=regime)
