import io
import json
import re
import heapq
from pathlib import Path
from typing import Dict, List, Any, Optional, Set
from collections import deque
from db.repository import Repository
from utils.helpers import (
    load_config as _load_config,
    demangle_scip_symbol,
    sanitize_docstring,
    resolve_symbol_in_repo,
    format_classification_badge,
)
from engines.registry import LanguageRegistry


class ContextCompiler:
    """
    Traverses call graph neighborhoods starting from a focal symbol using weighted
    Dijkstra exploration, extracts code blocks dynamically from the filesystem,
    auto-resolves referenced data-structure type signatures, and compiles a token-budgeted
    structured markdown context document for LLMs.
    """

    def __init__(self, repository: Repository, project_root: Path):
        self.repository = repository
        self.project_root = project_root

    def traverse_subgraph(
        self,
        focal_symbol: str,
        radius: int = 2,
        direction: str = "downstream"
    ) -> List[str]:
        """
        Traverses call graph edges using weighted Dijkstra traversal ordered by cumulative edge weight
        (semantic affinity) up to `radius` hops.
        direction can be "upstream" (callers), "downstream" (callees), or "both" (bidirectional).
        """
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
                incoming = self.repository.edges.get_incoming_edges(curr)
                for edge in incoming:
                    neighbor_edges.append((edge["source"], edge.get("weight", 1.0)))

            if direction in ("downstream", "both"):
                outgoing = self.repository.edges.get_outgoing_edges(curr)
                for edge in outgoing:
                    neighbor_edges.append((edge["target"], edge.get("weight", 1.0)))

            for neighbor, weight in neighbor_edges:
                edge_cost = 1.0 / max(weight, 0.01)
                new_cost = cum_cost + edge_cost
                if neighbor not in visited:
                    if neighbor not in best_costs or new_cost < best_costs[neighbor]:
                        best_costs[neighbor] = new_cost
                        seq += 1
                        heapq.heappush(pq, (new_cost, depth + 1, seq, neighbor))

        return result

    def resolve_referenced_types(self, focal_symbol: str, focal_info: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Resolves custom data-structure / class / struct type signatures referenced in focal symbol."""
        types_found = []
        seen_syms = set()

        outgoing = self.repository.edges.get_outgoing_edges(focal_symbol)
        type_targets = [e["target"] for e in outgoing if e.get("relation") in ("TypeDefinition", "Implements", "Inherits")]
        for tgt in type_targets:
            if tgt not in seen_syms:
                seen_syms.add(tgt)
                rec = self.repository.symbols.get_symbol(tgt)
                if rec and rec.get("kind") in ("Class", "Struct", "Interface", "Trait", "TypeAlias", "Enum"):
                    types_found.append(rec)

        sig = focal_info.get("signature") or ""
        if sig:
            builtins = {
                "String", "Int", "Integer", "Float", "Double", "Bool", "Boolean", "List", "Map", "Dict",
                "Set", "Optional", "Any", "Tuple", "Union", "None", "Result", "Ok", "Err", "Future",
                "Stream", "Task", "Void", "Dynamic", "Object", "Self", "Box", "Arc", "Rc", "Vec"
            }
            candidates = re.findall(r'\b[A-Z][a-zA-Z0-9_]+\b', sig)
            for cand in candidates:
                if cand in builtins:
                    continue
                matches = self.repository.symbols.search_symbols_keyword(cand, limit=3)
                for m in matches:
                    sym_id, fp, kind, s_sig, doc = m[0], m[1], m[2], m[3], m[4]
                    if sym_id not in seen_syms and kind in ("Class", "Struct", "Interface", "Trait", "TypeAlias", "Enum"):
                        clean = demangle_scip_symbol(sym_id)
                        short = clean.split(".")[-1]
                        if short == cand or clean.endswith(f".{cand}") or clean == cand:
                            seen_syms.add(sym_id)
                            types_found.append({
                                "symbol": sym_id,
                                "filepath": fp,
                                "kind": kind,
                                "signature": s_sig,
                                "docstring": doc
                            })
                            break
        return types_found

    def extract_raw_code(self, filepath: str, start_line: int, end_line: int) -> str:
        """
        Reads source code from disk using start_line and end_line coordinates.
        """
        full_path = self.project_root / filepath
        if not full_path.exists():
            return f"_Error: Source file '{filepath}' not found on disk._"
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            # 1-based indexing
            start_idx = max(0, start_line - 1)
            end_idx = min(len(lines), end_line)
            return "".join(lines[start_idx:end_idx]).rstrip()
        except Exception as e:
            return f"_Error reading code block: {e}_"

    def get_language_from_filepath(self, filepath: str) -> str:
        """Detect language from filepath using the language registry."""
        lang = LanguageRegistry.detect_language(filepath)
        return lang or "unknown"

    def generate_markdown(
        self,
        focal_symbol: str,
        traversed_symbols: List[str],
        metadata_map: Dict[str, Dict[str, Any]],
        resolution: str,
        direction: str,
        radius: int,
        max_tokens: int = 4000
    ) -> str:
        writer = io.StringIO()
        writer.write("# Dynamic Architectural Context Compilation\n")
        writer.write("Generated dynamically by the Arch-mcp Context Compiler.\n\n")

        # 0. Active System Ontology Configuration
        config = _load_config(self.project_root)
        if config:
            writer.write("## 0. Active System Ontology Configuration (Boundary Constraints)\n")
            writer.write("```json\n")
            writer.write(json.dumps(config.to_dict(), indent=2) + "\n")
            writer.write("```\n\n")

        # 1. Architectural Context Bounds
        clean_focal = demangle_scip_symbol(focal_symbol)
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

        focal_info = metadata_map.get(focal_symbol, {})
        if focal_symbol in metadata_map:
            self._write_node_details(writer, focal_info, force_full=True)
        else:
            writer.write(f"_Error: Focal target symbol `{clean_focal}` details not found in the index database._\n")

        # 2b. Auto-Include Referenced Data Structures & Type Signatures
        ref_types = self.resolve_referenced_types(focal_symbol, focal_info)
        if ref_types:
            writer.write("\n---\n")
            writer.write("## 2b. Referenced Data Structures & Type Signatures\n\n")
            for t in ref_types:
                clean_t = demangle_scip_symbol(t["symbol"])
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
            clean_sym = demangle_scip_symbol(sym)
            writer.write(f"### Neighbor #{neighbor_index}: `{clean_sym}`\n")

            if sym in metadata_map:
                node_data = metadata_map[sym]
                # Token estimation and progressive degradation
                current_tokens = len(writer.getvalue()) // 4
                is_degraded = False
                node_res = "full" if resolution == "full" else "signature"

                if node_res == "full":
                    # Estimate if full extraction will exceed token budget
                    defn = node_data.get("definition")
                    fp = node_data.get("filepath")
                    estimated_lines = (defn["end_line"] - defn["start_line"] + 1) if defn else 10
                    estimated_code_tokens = (estimated_lines * 40) // 4
                    if current_tokens + estimated_code_tokens > max_tokens:
                        node_res = "signature"
                        is_degraded = True

                self._write_node_details(writer, node_data, force_full=(node_res == "full"))
                if is_degraded:
                    writer.write(f"> _Progressive Degradation: Degraded to signature resolution to fit within token budget ({max_tokens} tokens)._\n\n")
            else:
                writer.write(f"- **Symbol ID**: `{clean_sym}`\n")
                writer.write("- **Status**: `External or Unindexed Symbol`\n\n")

        return writer.getvalue()

    def _write_node_details(self, writer: io.StringIO, node_info: Dict[str, Any], force_full: bool) -> None:
        filepath = node_info.get("filepath")
        kind = node_info.get("kind", "UnspecifiedKind")
        signature = node_info.get("signature")
        docstring = node_info.get("docstring")
        definition = node_info.get("definition")

        clean_sym = demangle_scip_symbol(node_info["symbol"])
        badge = format_classification_badge(node_info.get("classification"))
        badge_header = f" `{badge}`" if badge else ""
        writer.write(f"- **Symbol ID**: `{clean_sym}`{badge_header}\n")
        writer.write(f"- **Filepath**: `{filepath or 'External / Third-party Library'}`\n")
        writer.write(f"- **AST Kind**: `'{kind}'`\n")
        if badge:
            writer.write(f"- **Classification**: `{badge}`\n")

        # Surface diagnostics if present
        diags = self.repository.symbols.get_diagnostics_for_symbol(node_info["symbol"])
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

        if force_full and definition and filepath:
            start_line = definition["start_line"]
            end_line = definition["end_line"]
            raw_code = self.extract_raw_code(filepath, start_line, end_line)
            lang = self.get_language_from_filepath(filepath)
            
            writer.write("\n#### Active Code Block:\n")
            writer.write(f"```{lang}\n")
            writer.write(f"{raw_code}\n")
            writer.write("```\n\n")
        elif not force_full:
            writer.write("\n_Signature resolution mode: active code block suppressed._\n\n")
        elif not definition:
            writer.write("\n_No source code coordinates available (external dependency)._\n\n")

    def compile(
        self,
        focal_symbol: str,
        radius: int = 2,
        direction: str = "downstream",
        resolution: str = "full",
        out_filepath: Optional[str] = None,
        max_tokens: int = 4000
    ) -> str:
        """
        Compiles the architectural context for the focal symbol.
        Traverses graph using weighted Dijkstra, extracts code blocks, formats markdown,
        and bounds response within max_tokens budget.
        Returns the markdown string.
        """
        resolved = resolve_symbol_in_repo(self.repository, focal_symbol)
        actual_focal = resolved[0] if resolved else focal_symbol

        traversed_symbols = self.traverse_subgraph(actual_focal, radius, direction)
        # Filter out local symbols
        traversed_symbols = [s for s in traversed_symbols if not str(s).startswith("local ")]
        metadata_map = self.repository.symbols.get_symbols_metadata_batch(traversed_symbols)

        md_content = self.generate_markdown(
            actual_focal,
            traversed_symbols,
            metadata_map,
            resolution,
            direction,
            radius,
            max_tokens=max_tokens
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
