import random
from db.repository import Repository

def detect_communities(repository: Repository):
    """
    Groups repository symbols into cohesive communities using Label Propagation (LPA).
    """
    # Fetch symbols and edges using repository methods
    symbols_list = repository.graph.get_all_symbols()
    edges_list = repository.graph.get_edges()

    symbols = {item["symbol"]: item["filepath"] for item in symbols_list}
    edges = [(item["source"], item["target"], item["weight"]) for item in edges_list]

    # Build adjacency list with weights (undirected for community propagation)
    adj = {sym: {} for sym in symbols}
    for src, tgt, weight in edges:
        if src in adj and tgt in adj:
            adj[src][tgt] = max(adj[src].get(tgt, 0.0), weight)
            adj[tgt][src] = max(adj[tgt].get(src, 0.0), weight)

    # Calculate degree for each symbol (sum of incoming and outgoing edges)
    degrees = {sym: 0 for sym in symbols}
    for src, tgt, _ in edges:
        if src in degrees:
            degrees[src] += 1
        if tgt in degrees:
            degrees[tgt] += 1

    # Initialize labels to directory prefixes
    labels = {}
    for sym, fp in symbols.items():
        if fp:
            fp_norm = fp.replace("\\", "/")
            parts = fp_norm.split("/")
            if len(parts) > 1:
                labels[sym] = "/".join(parts[:-1]) + "/"
            else:
                labels[sym] = "./"
        else:
            labels[sym] = "external/"

    # Run LPA for 5 iterations
    # Seed random for determinism under tests
    random.seed(42)
    for _ in range(5):
        nodes = list(symbols.keys())
        random.shuffle(nodes)
        for u in nodes:
            neighbors = adj[u]
            if not neighbors:
                continue
            # Count neighbor label frequencies weighted by edge weights
            freq = {}
            for v, weight in neighbors.items():
                lbl = labels[v]
                freq[lbl] = freq.get(lbl, 0.0) + weight
            # Find maximum frequency label
            max_freq = max(freq.values())
            candidates = [lbl for lbl, count in freq.items() if count == max_freq]
            # Tie breaking: prefer current label if candidate, else deterministic choice
            if labels[u] in candidates:
                continue
            # Sort candidates for determinism
            candidates.sort()
            labels[u] = candidates[0]

    # Group nodes by community label
    communities = {}
    for sym, lbl in labels.items():
        communities.setdefault(lbl, []).append(sym)

    # Calculate inter-community connections (number of physical calls/edges)
    connections = {}
    for src, tgt, _ in edges:
        lbl_src = labels.get(src)
        lbl_tgt = labels.get(tgt)
        if lbl_src and lbl_tgt and lbl_src != lbl_tgt:
            connections.setdefault(lbl_src, {}).setdefault(lbl_tgt, 0)
            connections[lbl_src][lbl_tgt] += 1

    return communities, connections, degrees

