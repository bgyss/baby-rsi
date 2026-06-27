"""Built-in ML pack evaluator.

Behavior remains the existing controller-owned ``eval.py`` contract.
"""

from siro.packs import EvalPyAdapter, EvaluatorRegime


def get_adapter(regime: EvaluatorRegime) -> EvalPyAdapter:
    """Return the default eval.py adapter with the pack-declared regime."""
    return EvalPyAdapter(regime=regime)
