"""Objective test suite for task_001. The evaluator scores against these."""

from seed_solution import sum_list


def test_empty():
    assert sum_list([]) == 0


def test_integers():
    assert sum_list([1, 2, 3]) == 6


def test_floats():
    assert sum_list([0.5, 1.5]) == 2.0


def test_negatives():
    assert sum_list([-2, 2, -3]) == -3
