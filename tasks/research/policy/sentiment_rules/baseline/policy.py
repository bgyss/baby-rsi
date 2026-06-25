"""Seed sentiment policy for the `sentiment_rules` research task (intentionally weak).

It only looks for the single word "good", so it misses most positive phrasings and every
negation. The research org improves the ruleset to raise aggregate accuracy on a held-out
benchmark it never sees.
"""


def classify(text):
    """Return 1 for positive sentiment, 0 for negative."""
    return 1 if "good" in text.lower() else 0
