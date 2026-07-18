import io
import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from collections import deque
from db.repository import Repository
from utils.helpers import load_config as _load_config
from engines.registry import LanguageRegistry


class ContextCompiler:
    """
    Traverses call graph neighborhoods starting from a focal symbol,
    extracts code blocks dynamically from the filesystem, and compiles
    a structured markdown context document for LLMs.
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
        Traverses call graph edges using BFS starting from the focal_symbol up to `radius` hops.
        direction can be "upstream" (callers), "downstream" (callees), or "both" (bidirectional).
        """
        queue = deque([(focal_symbol, 0)])
        visited = {focal_symbol}
        result = []

        while queue:
            curr, depth = queue.popleft()
            result.append(curr)

            if depth >= radius:
                continue

            neighbors = set()
            # Upstream (Who calls curr)
            if direction in ("upstream", "both"):
                incoming = self.repository.edges.get_incoming_edges(curr)
                for edge in incoming:
                    neighbors.add(edge["source"])

            # Downstream (What does curr call)
            if direction in ("downstream", "both"):
                outgoing = self.repository.edges.get_outgoing_edges(curr)
                for edge in outgoing:
                    neighbors.add(edge["target"])

            for neighbor in neighbors:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, depth + 1))

        return result

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
        radius: int
    ) -> str:
        writer = io.StringIO()
        writer.write("# Dynamic Architectural Context Compilation\n")
        writer.write("Generated dynamically by the Arch-mcp Context Compiler.\n\n")

        # 0. Active System Ontology Configuration
        config = _load_config(self.project_root)
        if config:
            writer.write("## 0. Active System Ontology Configuration (Boundary Constraints)\n")
            writer.write("```json\n")
            writer.write(json.dumps(config, indent=2) + "\n")
            writer.write("```\n\n")

        # 1. Architectural Context Bounds
        writer.write("## 1. Architectural Context Bounds\n")
        writer.write(f"- **Focal Target**: `{focal_symbol}`\n")
        writer.write(f"- **Search Direction**: `{direction}`\n")
        writer.write(f"- **Traversed Radius**: `{radius}` hops\n")
        writer.write(f"- **Resolution Profile**: `{resolution}`\n")
        writer.write(f"- **Total Resolved Nodes**: `{len(traversed_symbols)}`\n\n")

        writer.write("---\n")
        writer.write("## 2. Focal Core Target Node\n")

        if focal_symbol in metadata_map:
            self._write_node_details(writer, metadata_map[focal_symbol], force_full=True)
        else:
            writer.write(f"_Error: Focal target symbol `{focal_symbol}` details not found in the index database._\n")

        writer.write("\n---\n")
        writer.write("## 3. Traversed Subgraph Neighbors\n\n")

        neighbor_index = 0
        for sym in traversed_symbols:
            if sym == focal_symbol:
                continue
            neighbor_index += 1
            writer.write(f"### Neighbor #{neighbor_index}: `{sym}`\n")

            if sym in metadata_map:
                node_res = "full" if resolution == "full" else "signature"
                self._write_node_details(writer, metadata_map[sym], force_full=(node_res == "full"))
            else:
                writer.write(f"- **Symbol ID**: `{sym}`\n")
                writer.write("- **Status**: `External or Unindexed Symbol`\n\n")

        return writer.getvalue()

    def _write_node_details(self, writer: io.StringIO, node_info: Dict[str, Any], force_full: bool) -> None:
        filepath = node_info.get("filepath")
        kind = node_info.get("kind", "UnspecifiedKind")
        signature = node_info.get("signature")
        docstring = node_info.get("docstring")
        definition = node_info.get("definition")

        writer.write(f"- **Symbol ID**: `{node_info['symbol']}`\n")
        writer.write(f"- **Filepath**: `{filepath or 'External / Third-party Library'}`\n")
        writer.write(f"- **AST Kind**: `'{kind}'`\n")

        if signature:
            writer.write(f"- **Signature**: `{signature}`\n")

        if docstring:
            clean_doc = docstring.strip().replace("\n", "\n  ")
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
        out_filepath: Optional[str] = None
    ) -> str:
        """
        Compiles the architectural context for the focal symbol.
        Traverses graph, extracts code blocks, formats markdown, writes to file if out_filepath is provided.
        Returns the markdown string.
        """
        traversed_symbols = self.traverse_subgraph(focal_symbol, radius, direction)
        metadata_map = self.repository.symbols.get_symbols_metadata_batch(traversed_symbols)
        
        md_content = self.generate_markdown(
            focal_symbol,
            traversed_symbols,
            metadata_map,
            resolution,
            direction,
            radius
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
