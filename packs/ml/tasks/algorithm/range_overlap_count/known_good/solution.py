def solve(intervals):
    total = 0
    for i, (a,b) in enumerate(intervals):
        for c,d in intervals[i+1:]:
            if max(a,c) <= min(b,d):
                total += 1
    return total
