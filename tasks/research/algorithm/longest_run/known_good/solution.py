def solve(values):
    best = cur = 0
    prev = object()
    for v in values:
        cur = cur + 1 if v == prev else 1
        best = max(best, cur)
        prev = v
    return best
