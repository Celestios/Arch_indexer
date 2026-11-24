"""Hierarchical bottom-up dendrogram aggregation with dominance gate and LCA placement."""
from collections import defaultdict
from typing import Dict, List, Tuple

from clustering.models import ClusterNode


def collapse_single_child_wrappers(node: ClusterNode) -> ClusterNode:
    """Collapses redundant single-child wrapper chains and recalculates level monotonically."""
    node.children = [collapse_single_child_wrappers(c) for c in node.children]
    if node.cluster_id != "root" and len(node.children) == 1:
        child = node.children[0]
        if child.children:
            node.children = child.children
            node.is_cycle = node.is_cycle or child.is_cycle
            node.is_singleton = False
    node.level = max((c.level for c in node.children), default=-1) + 1
    return node


def assign_hierarchical_ids(node: ClusterNode):
    """Assigns dot-delimited positional IDs (c1, c1.1, c1.2, etc.) deterministically."""
    node.children.sort(key=lambda c: (-len(c.symbol_ids), min(c.symbol_ids) if c.symbol_ids else ""))
    for i, child in enumerate(node.children):
        if node.cluster_id == "root":
            child.cluster_id = f"c{i + 1}"
            child.parent_id = "root"
        else:
            child.cluster_id = f"{node.cluster_id}.{i + 1}"
            child.parent_id = node.cluster_id
        assign_hierarchical_ids(child)


def run_hierarchical_aggregation(
    initial_nodes: List[ClusterNode],
    sym_to_id: Dict[str, int],
    undirected_aff: Dict[Tuple[int, int], float],
    dampened_out_weights: Dict[Tuple[int, int], float],
    max_passes: int = 8,
) -> ClusterNode:
    """
    Executes Passes L = 1..max_passes in O(E) sparse edge iterations per pass on the
    shared dampened affinity scale:
    - Phase A: Deterministic Louvain Modularity Local Moving (preserving internal self-loop mass)
    - Phase B: Dominance Gate (Direction-aware Hub & Orchestrator Ejection)
    - Phase C: Private-Dependency Absorption (symmetrical directed super-node adjacency)
    - Phase D: Super-Node Contraction & Natural LCA Placement
    """
    current_super_nodes = initial_nodes
    supernode_internal_weight: List[float] = [0.0] * len(current_super_nodes)

    for pass_num in range(1, max_passes + 1):
        P = len(current_super_nodes)
        if P <= 1:
            break

        sym_id_to_supernode: Dict[int, int] = {}
        for node_idx, s_node in enumerate(current_super_nodes):
            for s in s_node.symbol_ids:
                if s in sym_to_id:
                    sym_id_to_supernode[sym_to_id[s]] = node_idx

        node_adj: Dict[int, Dict[int, float]] = defaultdict(lambda: defaultdict(float))
        node_out_adj: Dict[int, Dict[int, float]] = defaultdict(lambda: defaultdict(float))
        node_in_adj: Dict[int, Dict[int, float]] = defaultdict(lambda: defaultdict(float))
        node_external_deg: List[float] = [0.0] * P

        for (u, v), w in undirected_aff.items():
            if u in sym_id_to_supernode and v in sym_id_to_supernode:
                su = sym_id_to_supernode[u]
                sv = sym_id_to_supernode[v]
                if su != sv:
                    node_adj[su][sv] += w
                    node_adj[sv][su] += w
                    node_external_deg[su] += w
                    node_external_deg[sv] += w
                elif pass_num == 1:
                    supernode_internal_weight[su] += w

        for (u, v), w in dampened_out_weights.items():
            if u in sym_id_to_supernode and v in sym_id_to_supernode:
                su = sym_id_to_supernode[u]
                sv = sym_id_to_supernode[v]
                if su != sv:
                    node_out_adj[su][sv] += w
                    node_in_adj[sv][su] += w

        node_deg: List[float] = [
            2.0 * supernode_internal_weight[i] + node_external_deg[i]
            for i in range(P)
        ]

        total_m = 0.5 * sum(node_deg)
        if total_m < 1e-12:
            break

        # Phase A: Deterministic Louvain Modularity Local Moving
        community: List[int] = list(range(P))
        comm_tot: List[float] = list(node_deg)

        for _ in range(20):
            moved_any = False
            for i in range(P):
                curr_c = community[i]
                weights_to_comm: Dict[int, float] = defaultdict(float)
                for j in sorted(node_adj[i].keys()):
                    weights_to_comm[community[j]] += node_adj[i][j]

                best_delta_Q = 0.0
                best_c = curr_c
                k_i = node_deg[i]
                k_i_in_curr = weights_to_comm.get(curr_c, 0.0)
                tot_curr_minus_i = comm_tot[curr_c] - k_i

                for cand_c in sorted(weights_to_comm.keys()):
                    if cand_c == curr_c:
                        continue
                    k_i_in_cand = weights_to_comm[cand_c]
                    tot_cand = comm_tot[cand_c]
                    delta_Q = ((k_i_in_cand - k_i_in_curr) / total_m) + (
                        (k_i * (tot_curr_minus_i - tot_cand)) / (2.0 * total_m * total_m)
                    )
                    if delta_Q > best_delta_Q + 1e-9:
                        best_delta_Q = delta_Q
                        best_c = cand_c

                if best_c != curr_c:
                    community[i] = best_c
                    comm_tot[curr_c] -= k_i
                    comm_tot[best_c] += k_i
                    moved_any = True

            if not moved_any:
                break

        comm_members: Dict[int, List[int]] = defaultdict(list)
        for i, c in enumerate(community):
            comm_members[c].append(i)

        # Phase B: Dominance Gate (Direction-aware Hub & Orchestrator Ejection)
        next_comm_id = P
        for _ in range(5):
            ejected_any = False
            for c_id in sorted(list(comm_members.keys())):
                members = comm_members.get(c_id, [])
                if len(members) < 2:
                    continue

                for u in list(members):
                    if len(members) < 2:
                        break

                    w_internal = sum(node_adj[u].get(v, 0.0) for v in members if v != u)

                    ext_inbound_comms = {
                        community[v]
                        for v, w in node_in_adj[u].items()
                        if w > 0
                    } - {c_id}

                    ext_outbound_comms = {
                        community[v]
                        for v, w in node_out_adj[u].items()
                        if w > 0
                    } - {c_id}

                    should_eject = False

                    # Shared Inbound Hub
                    if len(ext_inbound_comms) >= 2:
                        w_in_ext = sum(w for v, w in node_in_adj[u].items() if community[v] != c_id)
                        total_in_and_internal = w_in_ext + w_internal
                        if total_in_and_internal > 0 and (w_internal / total_in_and_internal) <= 0.50:
                            should_eject = True

                    # Callerless Multi-Subsystem Orchestrator
                    if not should_eject and len(node_in_adj[u]) == 0 and len(ext_outbound_comms) >= 2:
                        w_total_coupling = sum(node_adj[u].values())
                        if w_total_coupling > 0 and (w_internal / w_total_coupling) <= 0.50:
                            should_eject = True

                    if should_eject:
                        members.remove(u)
                        new_c = next_comm_id
                        next_comm_id += 1
                        community[u] = new_c
                        comm_members[new_c] = [u]
                        ejected_any = True
            if not ejected_any:
                break

        # Phase C: Private-Dependency Absorption (symmetrical directed super-node adjacency)
        for u in range(P):
            c_u = community[u]
            if len(comm_members[c_u]) != 1:
                continue

            caller_comms = {
                community[v]
                for v, w in node_in_adj[u].items()
                if v != u and w > 0
            }
            outbound_comms = {
                community[v]
                for v, w in node_out_adj[u].items()
                if v != u and w > 0
            }

            absorbed = False
            if len(caller_comms) == 1:
                target_c = next(iter(caller_comms))
                if len(comm_members[target_c]) >= 2 and len(outbound_comms - {target_c}) <= 1:
                    comm_members[c_u].remove(u)
                    if not comm_members[c_u]:
                        del comm_members[c_u]
                    community[u] = target_c
                    comm_members[target_c].append(u)
                    absorbed = True

            if not absorbed:
                w_total = sum(node_adj[u].values())
                if w_total > 0:
                    for cand_c in sorted(comm_members.keys()):
                        members = comm_members[cand_c]
                        if cand_c != c_u and len(members) >= 2:
                            w_in = sum(node_adj[u].get(v, 0.0) for v in members)
                            if (w_in / w_total) > 0.85:
                                comm_members[c_u].remove(u)
                                if not comm_members[c_u]:
                                    del comm_members[c_u]
                                community[u] = cand_c
                                comm_members[cand_c].append(u)
                                break

        # Phase D: Super-Node Contraction
        new_super_nodes: List[ClusterNode] = []
        new_internal_weights: List[float] = []
        any_merges = False

        sorted_comms = sorted(
            [m for m in comm_members.values() if m],
            key=lambda members: (
                -sum(len(current_super_nodes[m].symbol_ids) for m in members),
                min(min(current_super_nodes[m].symbol_ids) for m in members),
            ),
        )

        for members in sorted_comms:
            if len(members) == 1:
                idx = members[0]
                new_super_nodes.append(current_super_nodes[idx])
                new_internal_weights.append(supernode_internal_weight[idx])
            else:
                any_merges = True
                child_nodes = [current_super_nodes[m] for m in members]
                child_nodes.sort(key=lambda c: (-len(c.symbol_ids), min(c.symbol_ids) if c.symbol_ids else ""))
                all_syms = tuple(sorted(sum((list(c.symbol_ids) for c in child_nodes), [])))
                all_fps = tuple(sorted(set(sum((list(c.filepaths) for c in child_nodes), []))))
                parent_level = max(c.level for c in child_nodes) + 1
                parent_node = ClusterNode(
                    cluster_id="",
                    name="",
                    level=parent_level,
                    parent_id=None,
                    children=child_nodes,
                    symbol_ids=all_syms,
                    filepaths=all_fps,
                    is_cycle=False,
                    is_singleton=False,
                )
                new_super_nodes.append(parent_node)

                parent_internal = sum(supernode_internal_weight[m] for m in members)
                for i_pos, ma in enumerate(members):
                    for mb in members[i_pos + 1:]:
                        parent_internal += node_adj[ma].get(mb, 0.0)
                new_internal_weights.append(parent_internal)

        current_super_nodes = new_super_nodes
        supernode_internal_weight = new_internal_weights
        if not any_merges:
            break

    all_root_syms = tuple(sorted(sum((list(c.symbol_ids) for c in current_super_nodes), [])))
    all_root_fps = tuple(sorted(set(sum((list(c.filepaths) for c in current_super_nodes), []))))
    root = ClusterNode(
        cluster_id="root",
        name="root",
        level=max((c.level for c in current_super_nodes), default=0) + 1,
        parent_id=None,
        children=current_super_nodes,
        symbol_ids=all_root_syms,
        filepaths=all_root_fps,
        is_cycle=False,
        is_singleton=False,
    )

    root = collapse_single_child_wrappers(root)
    assign_hierarchical_ids(root)
    return root
