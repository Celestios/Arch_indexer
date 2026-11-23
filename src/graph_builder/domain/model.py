"""
Graph Model Builder.
Constructs pure file packages, nested class/symbol hierarchies, aggregated edges,
and global hub designations without hardcoded database assumptions.
"""

import os
import re
from typing import Dict, List, Any, Optional, Tuple, Union, Set
from pathlib import Path
from .types import NodeType, EdgeType, NODE_COLORS, NODE_SIZES, EDGE_COLORS
from .entities import GraphNode, GraphEdge
from utils.helpers import extract_code_slice


class GraphModel:
    """
    Constructs an interconnected architectural graph linking file packages,
    symbols, definitions, and aggregated call edges.
    """

    def __init__(
        self,
        include_occurrences: bool = False,
        max_refs_per_symbol: Optional[int] = 5,
        include_external: bool = False,
        exclude_tests: bool = True,
        exclude_parameters: bool = True,
        exclude_boilerplate: bool = True,
        scope: Optional[Union[str, List[str], Set[str]]] = None,
        hub_threshold: int = 6,
        project_root: Optional[Union[str, Path]] = None,
    ):
        self.include_occurrences = include_occurrences
        self.max_refs_per_symbol = max_refs_per_symbol
        self.include_external = include_external
        self.exclude_tests = exclude_tests
        self.exclude_parameters = exclude_parameters
        self.exclude_boilerplate = exclude_boilerplate
        self.hub_threshold = hub_threshold
        self.project_root = Path(project_root).resolve() if project_root else None

        if isinstance(scope, (list, set, tuple)):
            self.scopes = [s.replace("\\", "/").strip("/") for s in scope if s]
            self.scope = ",".join(self.scopes)
        elif isinstance(scope, str) and scope.strip() and scope.lower() not in ("all", "*"):
            if "," in scope:
                self.scopes = [s.strip().replace("\\", "/").strip("/") for s in scope.split(",") if s.strip()]
            else:
                self.scopes = [scope.replace("\\", "/").strip("/")]
            self.scope = scope
        else:
            self.scopes = None
            self.scope = None

        self.nodes: Dict[str, GraphNode] = {}
        self.edges: List[GraphEdge] = []
        self._edge_map: Dict[Tuple[str, str, str], GraphEdge] = {}
        self.packages: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def classify_symbol_kind(
        kind: str,
        is_external: bool,
        is_local: bool,
        raw_symbol: str = "",
    ) -> NodeType:
        if is_local:
            return NodeType.LOCAL
        if is_external:
            return NodeType.EXTERNAL

        if raw_symbol:
            parts = raw_symbol.split(" ")
            desc = parts[-1] if len(parts) >= 4 else raw_symbol
            clean_desc = desc.replace("`", "")
            if "()." in clean_desc or clean_desc.endswith("()"):
                if "__init__()." in clean_desc or "__init__()" in clean_desc:
                    return NodeType.CONSTRUCTOR
                return NodeType.METHOD if "#" in clean_desc else NodeType.FUNCTION
            elif clean_desc.endswith("#"):
                return NodeType.CLASS
            elif clean_desc.endswith(".") and not clean_desc.endswith("()."):
                return NodeType.FIELD
            elif clean_desc.endswith(":"):
                return NodeType.MODULE

        k = (kind or "").strip().lower()
        if k == "class":
            return NodeType.CLASS
        if k == "method":
            return NodeType.METHOD
        if k == "function":
            return NodeType.FUNCTION
        if k == "constructor":
            return NodeType.CONSTRUCTOR
        if k in ("field", "variable"):
            return NodeType.FIELD
        if k == "module":
            return NodeType.MODULE
        return NodeType.FUNCTION

    def _matches_scope(self, filepath: Optional[str]) -> bool:
        if not filepath:
            return False
        clean = filepath.replace("\\", "/")
        if self.exclude_tests:
            parts = clean.split("/")
            if "tests" in parts or "test" in parts:
                return False

        if self.exclude_boilerplate:
            from utils.exclusions import is_boilerplate
            if is_boilerplate(clean):
                return False

        if not self.scopes:
            return True

        # Normalize relative to project_root if clean is absolute
        rel_clean = clean
        if self.project_root:
            try:
                rel_clean = str(Path(clean).relative_to(self.project_root)).replace("\\", "/")
            except Exception:
                pass

        for s in self.scopes:
            if rel_clean.startswith(s + "/") or rel_clean == s or clean.startswith(s + "/") or clean == s:
                return True
        return False

    def add_node(self, node: GraphNode):
        if node.id not in self.nodes:
            self.nodes[node.id] = node

    def add_edge(
        self,
        source: str,
        target: str,
        edge_type: EdgeType,
        relation: str,
        weight: float = 1.0,
        dashed: bool = False,
        call_site: Optional[Tuple[int, int]] = None,
    ):
        if source not in self.nodes or target not in self.nodes:
            return
        if source == target:
            return

        key = (source, target, edge_type.value)
        if key in self._edge_map:
            edge = self._edge_map[key]
            edge.call_count += 1
            if call_site and call_site not in edge.call_sites:
                edge.call_sites.append(call_site)
            return

        edge = GraphEdge(
            source=source,
            target=target,
            type=edge_type,
            color=EDGE_COLORS.get(edge_type, "#94a3b8"),
            relation=relation,
            weight=weight,
            dashed=dashed,
            call_sites=[call_site] if call_site else [],
            call_count=1,
        )
        self._edge_map[key] = edge
        self.edges.append(edge)
        self.nodes[source].out_degree += 1
        self.nodes[target].in_degree += 1

    def build_from_reader(self, reader) -> "GraphModel":
        files = reader.fetch_files()
        symbols = reader.fetch_symbols()
        db_edges = reader.fetch_edges()
        symbol_defs = reader.fetch_symbol_definitions() if hasattr(reader, "fetch_symbol_definitions") else {}

        if not files:
            unique_fps = {s["filepath"] for s in symbols if s.get("filepath")}
            files = [
                {
                    "filepath": fp,
                    "language": "python",
                    "status": "COMPLIANT",
                    "filename": os.path.basename(fp),
                    "directory": os.path.dirname(fp) or ".",
                }
                for fp in sorted(unique_fps)
            ]

        scoped_files = [f for f in files if self._matches_scope(f["filepath"])]
        scoped_file_paths = {f["filepath"] for f in scoped_files}

        # 1. Store File Packages (pure containers, never graph nodes)
        for f in scoped_files:
            parts = f["filepath"].split("/")
            top_dir = "/".join(parts[:2]) if len(parts) > 2 else (parts[0] if len(parts) > 1 else "root")
            self.packages[f["filepath"]] = {
                "id": f["filepath"],
                "filepath": f["filepath"],
                "filename": f["filename"],
                "directory": f["directory"],
                "language": f["language"],
                "status": f["status"],
                "sha256": f.get("sha256"),
                "group": top_dir,
            }

        # Index classes per file to establish member containment
        file_classes: Dict[str, List[Dict[str, Any]]] = {}
        for s in symbols:
            desc = s["symbol"].split(" ")[-1].replace("`", "") if " " in s["symbol"] else s["symbol"]
            is_class = desc.endswith("#") or (s.get("kind") == "Class" and "()." not in desc)
            if is_class and s.get("filepath") in scoped_file_paths:
                file_classes.setdefault(s["filepath"], []).append(s)

        # 2. Add Symbol Nodes
        symbol_id_map: Dict[str, str] = {}
        for s in symbols:
            sym_filepath = s.get("filepath")
            if not sym_filepath or sym_filepath not in scoped_file_paths:
                continue

            if self.exclude_parameters and s.get("is_parameter"):
                continue

            if s.get("is_external") and not self.include_external:
                continue

            sid = f"sym:{s['symbol']}"
            symbol_id_map[s["symbol"]] = sid

            ntype = self.classify_symbol_kind(
                s["kind"], s["is_external"], s["is_local"], raw_symbol=s["symbol"]
            )
            group = sym_filepath

            base_size = NODE_SIZES.get(ntype, 6)
            conn_w = s.get("connection_weight", 0)
            node_size = base_size + min(conn_w * 0.5, 10)

            parent_cls_id = None
            if ntype in (NodeType.METHOD, NodeType.CONSTRUCTOR, NodeType.FIELD):
                f_classes = file_classes.get(sym_filepath, [])
                candidates = [c for c in f_classes if s["symbol"].startswith(c["symbol"]) and s["symbol"] != c["symbol"]]
                if candidates:
                    best_cls = max(candidates, key=lambda c: len(c["symbol"]))
                    parent_cls_id = f"sym:{best_cls['symbol']}"

            ports = s.get("ports") or {"inputs": [], "output": None}

            def_info = symbol_defs.get(s["symbol"])
            line = def_info["start_line"] if def_info else None
            col = def_info["start_col"] if def_info else None
            end_line = def_info["end_line"] if def_info else None
            code_text = None
            if sym_filepath and line and end_line:
                code_text = extract_code_slice(sym_filepath, line, end_line, project_root=self.project_root)

            node_label = s["label"]
            if (parent_cls_id or ntype in (NodeType.METHOD, NodeType.CONSTRUCTOR)) and "#" in node_label:
                node_label = node_label.split("#")[-1]
            if "." in node_label or "/" in node_label or "\\" in node_label:
                has_parens = node_label.endswith("()") or node_label.endswith("().")
                base = node_label[:-3] if node_label.endswith("().") else (node_label[:-2] if node_label.endswith("()") else node_label)
                leaf = re.split(r"[/:\\.]", base)[-1]
                if "#" in leaf:
                    leaf = leaf.split("#")[-1]
                node_label = (leaf + "()") if has_parens else leaf

            self.add_node(
                GraphNode(
                    id=sid,
                    label=node_label,
                    type=ntype,
                    color=NODE_COLORS[ntype],
                    val=node_size,
                    group=group,
                    filepath=sym_filepath,
                    line=line,
                    col=col,
                    end_line=end_line,
                    signature=s["signature"],
                    docstring=s["docstring"],
                    raw_symbol=s["symbol"],
                    code=code_text,
                    is_external=False,
                    is_local=s["is_local"],
                    parent_class=parent_cls_id,
                    ports=ports,
                    metadata={
                        "display_name": s["display_name"],
                        "kind": s["kind"],
                        "package": s["pkg"],
                    },
                )
            )

        # 3. Add Aggregated Edges with Call-Site Coordinates
        for e in db_edges:
            src_sym = e["source"]
            tgt_sym = e["target"]
            rel = e["relation"]

            src_id = symbol_id_map.get(src_sym)
            tgt_id = symbol_id_map.get(tgt_sym)

            if src_id and tgt_id:
                rel_lower = rel.lower()
                etype = EdgeType.INHERITS if ("inherit" in rel_lower or rel_lower == "implements") else EdgeType.CALLS
                coord = (e["line"], e["col"]) if e.get("line") is not None and e.get("col") is not None else None
                self.add_edge(
                    source=src_id,
                    target=tgt_id,
                    edge_type=etype,
                    relation=rel,
                    weight=e["weight"],
                    call_site=coord,
                )

        # 4. Tag High-Fan-In Hubs
        hub_ids = set()
        for node in self.nodes.values():
            if node.in_degree > self.hub_threshold:
                node.is_hub = True
                hub_ids.add(node.id)

        for edge in self.edges:
            if edge.target in hub_ids:
                edge.is_hub_stub = True
                tgt_node = self.nodes.get(edge.target)
                edge.hub_stub_target = tgt_node.label if tgt_node else edge.target

        # 5. Order Outgoing Calls Left-to-Right by Earliest Call-Site
        def edge_call_key(edge: GraphEdge):
            if edge.call_sites:
                earliest = min(edge.call_sites, key=lambda cs: (cs[0], cs[1]))
                return (earliest[0], earliest[1])
            return (999999, 999999)

        node_out_edges: Dict[str, List[GraphEdge]] = {}
        for edge in self.edges:
            node_out_edges.setdefault(edge.source, []).append(edge)

        for src, out_edges in node_out_edges.items():
            out_edges.sort(key=edge_call_key)
            for rank, edge in enumerate(out_edges):
                edge.metadata["seq_rank"] = rank

        self.edges.sort(key=lambda e: (e.source, e.metadata.get("seq_rank", 0)))

        # 6. Optional Occurrences
        if self.include_occurrences:
            occurrences = reader.fetch_occurrences(filepath_filter=self.scope)
            symbol_defs: Dict[str, List[str]] = {}
            symbol_ref_counts: Dict[str, int] = {}

            for occ in occurrences:
                sym_str = occ["symbol"]
                sym_id = symbol_id_map.get(sym_str)
                if not sym_id:
                    continue

                if occ["is_definition"]:
                    occ_id = f"occ:def:{occ['filepath']}:{occ['start_line']}:{occ['start_col']}"
                    symbol_defs.setdefault(sym_str, []).append(occ_id)
                    self.add_node(
                        GraphNode(
                            id=occ_id,
                            label=f"def @ L{occ['start_line']}:{occ['start_col']}",
                            type=NodeType.OCCURRENCE_DEF,
                            color=NODE_COLORS[NodeType.OCCURRENCE_DEF],
                            val=NODE_SIZES[NodeType.OCCURRENCE_DEF],
                            group=occ["filepath"],
                            filepath=occ["filepath"],
                            line=occ["start_line"],
                            col=occ["start_col"],
                            raw_symbol=sym_str,
                            metadata={"role": occ["role"], "action": "Definition"},
                        )
                    )
                    self.add_edge(
                        source=occ_id,
                        target=sym_id,
                        edge_type=EdgeType.DEFINES,
                        relation="defines",
                        weight=1.5,
                    )

            for occ in occurrences:
                sym_str = occ["symbol"]
                sym_id = symbol_id_map.get(sym_str)
                if not sym_id or occ["is_definition"]:
                    continue

                if self.max_refs_per_symbol is not None:
                    current_count = symbol_ref_counts.get(sym_str, 0)
                    if current_count >= self.max_refs_per_symbol:
                        continue
                    symbol_ref_counts[sym_str] = current_count + 1

                occ_id = f"occ:ref:{occ['filepath']}:{occ['start_line']}:{occ['start_col']}"
                self.add_node(
                    GraphNode(
                        id=occ_id,
                        label=f"ref @ L{occ['start_line']}:{occ['start_col']}",
                        type=NodeType.OCCURRENCE_REF,
                        color=NODE_COLORS[NodeType.OCCURRENCE_REF],
                        val=NODE_SIZES[NodeType.OCCURRENCE_REF],
                        group=occ["filepath"],
                        filepath=occ["filepath"],
                        line=occ["start_line"],
                        col=occ["start_col"],
                        raw_symbol=sym_str,
                        metadata={"role": occ["role"], "action": "Reference"},
                    )
                )
                self.add_edge(
                    source=occ_id,
                    target=sym_id,
                    edge_type=EdgeType.REFERENCES,
                    relation="references",
                    weight=1.0,
                )
                for def_occ_id in symbol_defs.get(sym_str, []):
                    self.add_edge(
                        source=occ_id,
                        target=def_occ_id,
                        edge_type=EdgeType.REF_TO_DEF,
                        relation="refers_to_def",
                        weight=0.8,
                        dashed=True,
                    )

        return self

    def to_dict(self) -> Dict[str, Any]:
        type_counts: Dict[str, int] = {}
        for n in self.nodes.values():
            t = n.type.value if isinstance(n.type, NodeType) else str(n.type)
            type_counts[t] = type_counts.get(t, 0) + 1

        edge_counts: Dict[str, int] = {}
        for e in self.edges:
            et = e.type.value if isinstance(e.type, EdgeType) else str(e.type)
            edge_counts[et] = edge_counts.get(et, 0) + 1

        return {
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "links": [e.to_dict() for e in self.edges],
            "packages": list(self.packages.values()),
            "project_root": str(self.project_root) if self.project_root else None,
            "scope": self.scope,
            "stats": {
                "total_nodes": len(self.nodes),
                "total_edges": len(self.edges),
                "packages_count": len(self.packages),
                "node_types": type_counts,
                "edge_types": edge_counts,
            },
        }


