import heapq
import io
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from db.repository import Repository
from engines.polymorphism import IMPLEMENTS_RELATION, expand_virtual_neighbors
from engines.registry import LanguageRegistry
from utils.helpers import (
    extract_code_slice,
    format_classification_badge,
    load_config as _load_config,
    sanitize_docstring,
)
from utils.symbol_id import canonical_display_name, parse_canonical_id


class ContextCompiler:
    """Traverses call graph neighborhoods via weighted Dijkstra and compiles bounded markdown context."""

    def __init__(self, repository: Repository, project_root: Path):
        self.repository = repository
        self.project_root = project_root

    def extract_raw_code(self, filepath: str, start_line: int, end_line: int) -> str:
        code = extract_code_slice(filepath, start_line, end_line, project_root=self.project_root)
        if code is None:
            return f"_Error: Source file '{filepath}' not found on disk._"
        return code

    def traverse_subgraph(
        self,
        focal_symbol: str,
        radius: int = 2,
        direction: str = "downstream",
    ) -> List[str]:
        pq = [(0.0, 0, 0, focal_symbol)]
        best_costs = {focal_symbol: 0.0}
        visited = set()
        result = []
        seq = 0

        while pq:
            cum_cost, depth, _, curr = heapq.heappop(pq)
            if curr in visited:
                continue
            visited.add(curr)
            result.append(curr)

            if depth >= radius:
                continue

            neighbor_edges = []
            if direction in ("upstream", "both"):
                for edge in self.repository.graph.get_edges(target=curr):
                    if edge.get("relation") != IMPLEMENTS_RELATION:
                        neighbor_edges.append((edge["source"], edge.get("weight", 1.0)))
            if direction in ("downstream", "both"):
                for edge in self.repository.graph.get_edges(source=curr):
                    if edge.get("relation") != IMPLEMENTS_RELATION:
                        neighbor_edges.append((edge["target"], edge.get("weight", 1.0)))
            for v_neighbor, v_weight, _ in expand_virtual_neighbors(self.repository, curr, direction):
                neighbor_edges.append((v_neighbor, v_weight))

            for neighbor, weight in neighbor_edges:
                new_cost = cum_cost + 1.0 / max(weight, 0.01)
                if neighbor not in visited and (neighbor not in best_costs or new_cost < best_costs[neighbor]):
                    best_costs[neighbor] = new_cost
                    seq += 1
                    heapq.heappush(pq, (new_cost, depth + 1, seq, neighbor))

        return result

    def resolve_referenced_types(self, focal_symbol: str, focal_info: Dict[str, Any]) -> List[Dict[str, Any]]:
        types_found = []
        seen_syms = set()
        type_kinds = ("Class", "Struct", "Interface", "Trait", "TypeAlias", "Enum")

        outgoing = self.repository.graph.get_edges(source=focal_symbol)
        type_targets = [
            e["target"]
            for e in outgoing
            if e.get("relation") in ("TypeDefinition", "Implements", "Inherits")
        ]
        for tgt in type_targets:
            if tgt not in seen_syms:
                seen_syms.add(tgt)
                rec = self.repository.graph.get_symbol(tgt)
                if rec and rec.get("kind") in type_kinds:
                    types_found.append(rec)

        sig = focal_info.get("signature") or ""
        if sig:
            builtins = {
                "String", "Int", "Integer", "Float", "Double", "Bool", "Boolean", "List", "Map", "Dict",
                "Set", "Optional", "Any", "Tuple", "Union", "None", "Result", "Ok", "Err", "Future",
                "Stream", "Task", "Void", "Dynamic", "Object", "Self", "Box", "Arc", "Rc", "Vec",
            }
            for cand in re.findall(r"\b[A-Z][a-zA-Z0-9_]+\b", sig):
                if cand in builtins:
                    continue
                for m in self.repository.graph.search_symbols(cand, limit=5):
                    sym_id = m.get("symbol")
                    if sym_id and sym_id not in seen_syms and m.get("kind") in type_kinds:
                        leaf = m.get("name") or parse_canonical_id(sym_id)[2]
                        if leaf == cand:
                            seen_syms.add(sym_id)
                            types_found.append({
                                "symbol": sym_id,
                                "name": leaf,
                                "filepath": m.get("filepath"),
                                "kind": m.get("kind"),
                                "signature": m.get("signature"),
                                "docstring": m.get("docstring"),
                            })
                            break
        return types_found

    def get_language_from_filepath(self, filepath: str) -> str:
        return LanguageRegistry.detect_language(filepath) or "unknown"

    def generate_markdown(
        self,
        focal_symbol: str,
        traversed_symbols: List[str],
        metadata_map: Dict[str, Dict[str, Any]],
        resolution: str,
        direction: str,
        radius: int,
        max_tokens: int = 4000,
        diagnostics_map: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    ) -> str:
        diags_lookup = diagnostics_map or {}
        writer = io.StringIO()
        writer.write("# Dynamic Architectural Context Compilation\n")
        writer.write("Generated dynamically by the Arch-mcp Context Compiler.\n\n")

        config = _load_config(self.project_root)
        if config:
            writer.write("## 0. Active System Ontology Configuration (Boundary Constraints)\n")
            writer.write("```json\n")
            writer.write(json.dumps(config.to_dict(), indent=2) + "\n")
            writer.write("```\n\n")

        focal_info = metadata_map.get(focal_symbol, {})
        clean_focal = canonical_display_name(focal_symbol, focal_info.get("name"))
        clean_traversed = [s for s in traversed_symbols if not str(s).startswith("local ")]
        writer.write("## 1. Architectural Context Bounds\n")
        writer.write(f"- **Focal Target**: `{clean_focal}`\n")
        writer.write(f"- **Search Direction**: `{direction}`\n")
        writer.write(f"- **Traversed Radius**: `{radius}` hops\n")
        writer.write(f"- **Resolution Profile**: `{resolution}`\n")
        writer.write(f"- **Token Budget**: `{max_tokens}` tokens\n")
        writer.write(f"- **Total Resolved Nodes**: `{len(clean_traversed)}`\n\n")

        writer.write("---\n")
        writer.write("## 2. Focal Core Target Node\n")

        if focal_symbol in metadata_map:
            self._write_node_details(writer, focal_info, force_full=True, diagnostics_map=diags_lookup)
        else:
            writer.write(f"_Error: Focal target symbol `{clean_focal}` details not found in the index database._\n")

        ref_types = self.resolve_referenced_types(focal_symbol, focal_info)
        if ref_types:
            writer.write("\n---\n")
            writer.write("## 2b. Referenced Data Structures & Type Signatures\n\n")
            for t in ref_types:
                clean_t = canonical_display_name(t["symbol"], t.get("name"))
                writer.write(f"### Type: `{clean_t}`\n")
                writer.write(f"- **Filepath**: `{t.get('filepath') or 'External'}`\n")
                writer.write(f"- **AST Kind**: `'{t.get('kind', 'Type')}'`\n")
                if t.get("signature"):
                    writer.write(f"- **Signature**: `{t['signature']}`\n")
                if t.get("docstring"):
                    writer.write(f"- **Docstring**: {sanitize_docstring(t['docstring'])}\n")
                writer.write("\n")

        writer.write("---\n")
        writer.write("## 3. Traversed Subgraph Neighbors\n\n")

        neighbor_index = 0
        for sym in clean_traversed:
            if sym == focal_symbol:
                continue
            neighbor_index += 1
            node_data = metadata_map.get(sym)
            clean_sym = canonical_display_name(sym, node_data.get("name") if node_data else None)
            writer.write(f"### Neighbor #{neighbor_index}: `{clean_sym}`\n")

            if node_data:
                current_tokens = len(writer.getvalue()) // 4
                is_degraded = False
                node_res = "full" if resolution == "full" else "signature"

                if node_res == "full":
                    start_line = node_data.get("start_line")
                    end_line = node_data.get("end_line")
                    estimated_lines = (end_line - start_line + 1) if (start_line and end_line) else 10
                    if current_tokens + (estimated_lines * 40) // 4 > max_tokens:
                        node_res = "signature"
                        is_degraded = True

                self._write_node_details(
                    writer,
                    node_data,
                    force_full=(node_res == "full"),
                    diagnostics_map=diags_lookup,
                )
                if is_degraded:
                    writer.write(
                        f"> _Progressive Degradation: Degraded to signature resolution to fit within token budget ({max_tokens} tokens)._\n\n"
                    )
            else:
                writer.write(f"- **Symbol ID**: `{clean_sym}`\n")
                writer.write("- **Status**: `External or Unindexed Symbol`\n\n")

        return writer.getvalue()

    def _write_node_details(
        self,
        writer: io.StringIO,
        node_info: Dict[str, Any],
        force_full: bool,
        diagnostics_map: Dict[str, List[Dict[str, Any]]],
    ) -> None:
        filepath = node_info.get("filepath")
        kind = node_info.get("kind", "UnspecifiedKind")
        signature = node_info.get("signature")
        docstring = node_info.get("docstring")
        start_line = node_info.get("start_line")
        end_line = node_info.get("end_line")

        clean_sym = canonical_display_name(node_info["symbol"], node_info.get("name"))
        badge = format_classification_badge(node_info.get("classification"))
        badge_header = f" `{badge}`" if badge else ""
        writer.write(f"- **Symbol ID**: `{clean_sym}`{badge_header}\n")
        writer.write(f"- **Filepath**: `{filepath or 'External / Third-party Library'}`\n")
        writer.write(f"- **AST Kind**: `'{kind}'`\n")
        if badge:
            writer.write(f"- **Classification**: `{badge}`\n")

        diags = diagnostics_map.get(node_info["symbol"], [])
        if diags:
            writer.write("- **Compiler Diagnostics**:\n")
            for d in diags:
                code_str = f" [{d['code']}]" if d.get("code") else ""
                writer.write(f"  * `{d['severity']}`{code_str} L{d['line']}:{d['col']}: {d['message']}\n")

        if signature:
            writer.write(f"- **Signature**: `{signature}`\n")

        if docstring:
            clean_doc = sanitize_docstring(docstring).strip().replace("\n", "\n  ")
            writer.write(f"- **Docstring**:\n  {clean_doc}\n")
        else:
            writer.write("- **Docstring**: _No docstring available._\n")

        if force_full and start_line and end_line and filepath:
            raw_code = extract_code_slice(filepath, start_line, end_line, project_root=self.project_root)
            if raw_code is None:
                raw_code = f"_Error: Source file '{filepath}' not found on disk._"
            lang = self.get_language_from_filepath(filepath)
            writer.write("\n#### Active Code Block:\n")
            writer.write(f"```{lang}\n")
            writer.write(f"{raw_code}\n")
            writer.write("```\n\n")
        elif not force_full:
            writer.write("\n_Signature resolution mode: active code block suppressed._\n\n")
        else:
            writer.write("\n_No source code coordinates available (external dependency)._\n\n")

    def compile(
        self,
        focal_symbol: str,
        radius: int = 2,
        direction: str = "downstream",
        resolution: str = "full",
        out_filepath: Optional[str] = None,
        max_tokens: int = 4000,
    ) -> str:
        resolved = self.repository.graph.resolve_symbol(focal_symbol)
        actual_focal = resolved["symbol"] if resolved else focal_symbol

        traversed_symbols = [
            s for s in self.traverse_subgraph(actual_focal, radius, direction)
            if not str(s).startswith("local ")
        ]
        metadata_map = self.repository.graph.get_symbols_by_ids(traversed_symbols)
        diagnostics_map = self.repository.quality.get_diagnostics_batch(traversed_symbols)

        md_content = self.generate_markdown(
            actual_focal,
            traversed_symbols,
            metadata_map,
            resolution,
            direction,
            radius,
            max_tokens=max_tokens,
            diagnostics_map=diagnostics_map,
        )

        if out_filepath:
            out_path = Path(out_filepath)
            if not out_path.is_absolute():
                out_path = self.project_root / out_path
            try:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(md_content, encoding="utf-8")
            except Exception as e:
                md_content = f"> [!WARNING]\n> Failed to write context to file: {e}\n\n" + md_content

        return md_content
