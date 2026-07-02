from collections import deque
from typing import List
import hashlib


def bfs_shortest_path(source: str, sink: str, call_graph: dict) -> List[str]:
    """BFS shortest path in a directed graph (adjacency list)."""
    if source not in call_graph and source != sink:
        return []

    visited = {source}
    queue = deque([(source, [source])])

    while queue:
        current, path = queue.popleft()
        if current == sink:
            return path
        for neighbor in call_graph.get(current, []):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, path + [neighbor]))

    return []


def make_surface_id(filepath: str, name: str) -> str:
    """Generate unique surface ID from filepath and name."""
    raw = f"{filepath}::{name}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
