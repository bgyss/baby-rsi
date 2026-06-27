def solve(values, target):
    seen = set()
    for v in values:
        if target - v in seen:
            return True
        seen.add(v)
    return False
