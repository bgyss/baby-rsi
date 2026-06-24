"""Seed implementation for task_001. Intentionally naive; the loop improves it."""


def sum_list(values):
    total = 0
    for v in values:
        total = total + v
    return total
