"""Iterative non-recursive Tarjan's Strongly Connected Components (SCC) algorithm."""
from typing import Dict, List, Set


def iterative_tarjan_scc(nodes: List[int], adj: Dict[int, List[int]]) -> List[List[int]]:
    """
    Computes Strongly Connected Components (SCC) using an explicit call stack.
    Immune to Python recursion limits. Complexity: O(V + E).
    """
    index = 0
    indices: Dict[int, int] = {}
    lowlink: Dict[int, int] = {}
    on_stack: Set[int] = set()
    stack: List[int] = []
    sccs: List[List[int]] = []

    for node in sorted(nodes):
        if node in indices:
            continue
        call_stack = [(node, 0)]
        indices[node] = index
        lowlink[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)

        while call_stack:
            u, edge_idx = call_stack[-1]
            neighbors = adj.get(u, [])
            if edge_idx < len(neighbors):
                v = neighbors[edge_idx]
                call_stack[-1] = (u, edge_idx + 1)
                if v not in indices:
                    indices[v] = index
                    lowlink[v] = index
                    index += 1
                    stack.append(v)
                    on_stack.add(v)
                    call_stack.append((v, 0))
                elif v in on_stack:
                    lowlink[u] = min(lowlink[u], indices[v])
            else:
                call_stack.pop()
                if call_stack:
                    parent, _ = call_stack[-1]
                    lowlink[parent] = min(lowlink[parent], lowlink[u])
                if lowlink[u] == indices[u]:
                    scc: List[int] = []
                    while True:
                        w = stack.pop()
                        on_stack.remove(w)
                        scc.append(w)
                        if w == u:
                            break
                    sccs.append(scc)
    return sccs
