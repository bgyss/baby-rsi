def solve(values):
    best = cur = values[0] if values else 0
    for v in values[1:]:
        cur = max(v, cur + v)
        best = max(best, cur)
    return best
