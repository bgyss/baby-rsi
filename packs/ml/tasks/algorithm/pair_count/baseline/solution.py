"""Seed implementation for the `pair_count` research task (intentionally naive).

Counts unordered index pairs (i < j) whose values sum to ``target`` by scanning every
pair — correct, but quadratic. The research org is asked to keep it correct while
reducing the work it does (measured as executed source lines on a fixed workload).
"""


def count_pairs(nums, target):
    count = 0
    for i in range(len(nums)):
        for j in range(i + 1, len(nums)):
            if nums[i] + nums[j] == target:
                count += 1
    return count
