"""
Compact String-Interned Graph Serializer.
Serializes 2D hierarchical folder zone enclosures and parent-to-child funnel connectors.
"""

import json
from typing import Dict, List, Any


def compress_circuit_data(circuit_data: Dict[str, Any]) -> Dict[str, Any]:
    nodes = circuit_data.get("nodes", [])
    links = circuit_data.get("links", [])
    packages = circuit_data.get("packages", [])
    banners = circuit_data.get("zone_banners", [])

    string_pool: List[str] = []
    string_to_idx: Dict[str, int] = {}

    def intern(s: Any) -> int:
        if s is None:
            return -1
        s_str = str(s)
        if s_str not in string_to_idx:
            string_to_idx[s_str] = len(string_pool)
            string_pool.append(s_str)
        return string_to_idx[s_str]

    type_map = {
        "file": 0, "class": 1, "function": 2, "method": 3, "constructor": 4,
        "field": 5, "module": 6, "occurrence_def": 7, "occurrence_ref": 8,
        "external": 9, "local": 10,
    }
    edge_map = {
        "calls": 0, "defines": 1, "references": 2, "ref_to_def": 3,
        "contains": 4, "inherits": 5, "located_in": 6,
    }

    node_id_to_idx = {n["id"]: i for i, n in enumerate(nodes)}

    compact_nodes = []
    for n in nodes:
        t_code = type_map.get(n.get("type"), 1)
        f_idx = intern(n.get("filepath"))
        sig_idx = intern(n.get("signature"))
        sym_idx = intern(n.get("raw_symbol"))
        doc_idx = intern(n.get("docstring"))
        line = n.get("line") if n.get("line") is not None else -1
        col = n.get("col") if n.get("col") is not None else -1
        is_hub = 1 if n.get("is_hub") else 0

        ports = n.get("ports", {}) or {}
        inputs_json = json.dumps(ports.get("inputs", [])) if ports.get("inputs") else ""
        in_ports_idx = intern(inputs_json) if inputs_json else -1
        out_type_idx = intern(ports.get("output")) if ports.get("output") else -1
        code_idx = intern(n.get("code"))
        end_line = n.get("end_line") if n.get("end_line") is not None else -1

        compact_nodes.append([
            n.get("label", ""),
            t_code,
            int(n.get("x", 0)),
            int(n.get("y", 0)),
            int(n.get("width", 12)),
            int(n.get("height", 12)),
            f_idx,
            line,
            col,
            sig_idx,
            sym_idx,
            doc_idx,
            is_hub,
            in_ports_idx,
            out_type_idx,
            code_idx,
            end_line,
        ])

    compact_links = []
    for l in links:
        s_id = l["source"] if isinstance(l["source"], str) else l["source"]["id"]
        t_id = l["target"] if isinstance(l["target"], str) else l["target"]["id"]
        s_idx = node_id_to_idx.get(s_id)
        t_idx = node_id_to_idx.get(t_id)
        if s_idx is not None and t_idx is not None:
            e_code = edge_map.get(l.get("type"), 0)
            call_count = int(l.get("call_count", 1))
            is_hub_stub = 1 if l.get("is_hub_stub") else 0
            hub_tgt_idx = intern(l.get("hub_stub_target"))
            waypoints = l.get("waypoints", [])
            compact_links.append([
                s_idx,
                t_idx,
                e_code,
                call_count,
                is_hub_stub,
                waypoints,
                hub_tgt_idx,
            ])

    compact_packages = []
    for p in packages:
        classes_raw = p.get("classes", [])
        classes_data = [
            [intern(c["label"]), int(c["x"]), int(c["y"]), int(c["width"]), int(c["height"]), intern(c["id"])]
            for c in classes_raw
        ]
        compact_packages.append([
            intern(p.get("id")),
            int(p.get("x", 0)),
            int(p.get("y", 0)),
            int(p.get("width", 260)),
            int(p.get("height", 100)),
            int(p.get("zone", 0)),
            intern(p.get("color", "#38bdf8")),
            intern(p.get("filename", "")),
            int(p.get("tab_w", 120)),
            classes_data,
        ])

    compact_banners = []
    for b in banners:
        # [name_idx, color_idx, y, file_count, x, width, height, col_idx, parent_x, parent_y]
        compact_banners.append([
            intern(b.get("name")),
            intern(b.get("color")),
            int(b.get("y", 0)),
            int(b.get("file_count", 0)),
            int(b.get("x", 100)),
            int(b.get("width", 600)),
            int(b.get("height", 200)),
            int(b.get("col_idx", 0)),
            int(b.get("parent_x", -1)),
            int(b.get("parent_y", -1)),
        ])

    return {
        "strings": string_pool,
        "nodes": compact_nodes,
        "links": compact_links,
        "packages": compact_packages,
        "banners": compact_banners,
        "trunk_highways": circuit_data.get("trunk_highways", []),
        "board_width": int(circuit_data.get("board_width", 3200)),
        "board_height": int(circuit_data.get("board_height", 2000)),
        "stats": {
            "total_nodes": len(compact_nodes),
            "total_edges": len(compact_links),
            "packages_count": len(compact_packages),
        },
    }
