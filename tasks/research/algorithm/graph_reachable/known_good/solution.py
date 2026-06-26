def solve(edges, start, target):
    graph = {}
    for a,b in edges:
        graph.setdefault(a, []).append(b)
    todo = [start]
    seen = set()
    while todo:
        node = todo.pop()
        if node == target:
            return True
        if node in seen:
            continue
        seen.add(node)
        todo.extend(graph.get(node, []))
    return False
