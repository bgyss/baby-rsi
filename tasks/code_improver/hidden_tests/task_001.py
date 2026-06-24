"""Hidden test suite for task_001 — held out *outside* the task directory.

These tests are never copied into the task dir and never placed in a model prompt;
the controller's hidden-test gate (Goal 04) runs them in the sandbox before
promoting a candidate. A candidate that overfits the visible ``tests.py`` (e.g. by
hard-coding the visible answers) fails here, which is exactly the point: promotion
requires generalization, not memorization (``docs/05_evaluation_and_safety_gates.md``).
"""

from seed_solution import sum_list


def test_large_range():
    assert sum_list(list(range(1000))) == 499500


def test_mixed_int_and_float():
    assert sum_list([1, 2.5, -3, 0.5]) == 1.0


def test_single_element():
    assert sum_list([42]) == 42


def test_all_negative():
    assert sum_list([-1, -2, -3, -4]) == -10
