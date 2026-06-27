def solve(values, k):
    return sum(sorted(values, reverse=True)[:k])
