from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Set
from pathlib import Path
from collections import deque

from .dataflow import FlowStep
from .graph_utils import bfs_shortest_path


class CombinedDataflowTracer:
    """
    Language-agnostic data flow tracer that combines multiple backends:
    - Dart analyzer for .dart files
    - CodeQL for languages with databases (rust, go, java, etc.)
    - SCIP edges as fallback for any language
    - FFI_Binds edges to bridge between languages

    Usage:
        tracer = CombinedDataflowTracer(
            project_root=...,
            arch_dir=...,
            analyzer_db=dart_analyzer_db,   # Optional: for Dart
            codeql_wrappers={               # Optional: per-language CodeQL
                "rust": codeql_rust,
                "go": codeql_go,
            },
            repository=scip_repository       # Optional: SCIP edges
        )
        steps = tracer.trace("dart::main", "rust::process")
    """

    # Language detection from file extension
    EXTENSION_LANGUAGE_MAP = {
        ".dart": "dart",
        ".rs": "rust",
        ".go": "go",
        ".java": "java",
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".rb": "ruby",
        ".swift": "swift",
    }

    def __init__(self, project_root: Path, arch_dir: Path,
                 analyzer_db=None, codeql_wrappers: Dict[str, Any] = None,
                 repository=None):
        self.project_root = project_root
        self.arch_dir = arch_dir
        self.analyzer_db = analyzer_db          # DartAnalyzerDB (optional)
        self.codeql_wrappers = codeql_wrappers or {}  # {language: CodeQlWrapper}
        self.repository = repository             # Repository (SCIP data)

    def trace(self, source_symbol: str, sink_symbol: str) -> List[FlowStep]:
        """
        Find data flow path from source to sink across languages.
        Auto-detects languages and uses appropriate backends.
        """
        # 1. Detect languages for source and sink
        source_lang = self._detect_language_from_symbol(source_symbol)
        sink_lang = self._detect_language_from_symbol(sink_symbol)

        # 2. Build combined call graph from all sources
        call_graph = self._build_combined_call_graph(source_lang, sink_lang)

        # 3. BFS shortest path across combined graph
        path = self._find_path(source_symbol, sink_symbol, call_graph)

        # 4. Resolve locations from appropriate databases
        return self._resolve_locations(path)

    def _build_combined_call_graph(self, source_lang: str, sink_lang: str) -> dict:
        """
        Merge edges from all available sources:
        - Dart analyzer typed_edges (for .dart files)
        - CodeQL databases (for each language with a database)
        - SCIP edges (fallback for any language)
        - FFI_Binds (cross-language bridge)
        """
        graph = {}

        # 1. Load Dart typed edges from analyzer DB
        if self.analyzer_db:
            self._load_dart_edges(graph)

        # 2. Load CodeQL edges for each available language
        for lang, codeql in self.codeql_wrappers.items():
            if codeql and codeql.is_available():
                self._load_codeql_edges(graph, lang, codeql)

        # 3. Load SCIP edges (Calls, FFI_Binds) - works for all languages
        if self.repository:
            self._load_scip_edges(graph)

        return graph

    def _load_dart_edges(self, graph: dict):
        """Load Dart-specific typed edges from analyzer DB."""
        try:
            with self.analyzer_db.session() as conn:
                rows = conn.execute("SELECT source_id, target_id FROM typed_edges").fetchall()
                for row in rows:
                    graph.setdefault(row['source_id'], []).append(row['target_id'])
        except Exception as e:
            print(f"[CombinedTracer] Warning: Failed to load Dart edges: {e}")

    def _load_codeql_edges(self, graph: dict, language: str, codeql):
        """Load language-specific edges from CodeQL database."""
        # Check for language-specific or generic database
        db_dir = self.arch_dir / f"codeql_db_{language}"
        if not db_dir.exists():
            db_dir = self.arch_dir / "codeql_db"
        if not db_dir.exists():
            return

        try:
            import tempfile
            from pathlib import Path

            # Language-agnostic call graph query
            ql_content = f"""
            import {language}
            from Function caller, Function callee
            where caller.calls(callee)
            select caller.getName(), callee.getName()
            """

            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                ql_file = temp_path / "callgraph.ql"
                bqrs_file = temp_path / "callgraph.bqrs"
                json_file = temp_path / "callgraph.json"

                ql_file.write_text(ql_content)

                if codeql.run_query(db_dir, ql_file, bqrs_file):
                    result = codeql.decode_bqrs(bqrs_file, json_file)
                    if result and "tuples" in result:
                        for row in result["tuples"]:
                            if len(row) >= 2:
                                source = row[0].get("value", "") if isinstance(row[0], dict) else str(row[0])
                                target = row[1].get("value", "") if isinstance(row[1], dict) else str(row[1])
                                if source and target:
                                    graph.setdefault(source, []).append(target)
        except Exception as e:
            print(f"[CombinedTracer] Warning: Failed to load CodeQL edges for {language}: {e}")

    def _load_scip_edges(self, graph: dict):
        """Load SCIP edges (Calls, FFI_Binds) for cross-language bridging."""
        try:
            with self.repository.db_conn.session() as conn:
                rows = conn.execute(
                    "SELECT source, target, relation FROM edges"
                ).fetchall()
                for row in rows:
                    source, target, relation = row[0], row[1], row[2]
                    graph.setdefault(source, []).append(target)
        except Exception as e:
            print(f"[CombinedTracer] Warning: Failed to load SCIP edges: {e}")

    def _find_path(self, source: str, sink: str, call_graph: dict) -> List[str]:
        """BFS shortest path in combined call graph."""
        return bfs_shortest_path(source, sink, call_graph)

    def _resolve_locations(self, path: List[str]) -> List[FlowStep]:
        """Convert symbol IDs to FlowStep with file/line from appropriate databases."""
        steps = []
        for symbol_id in path:
            language = self._detect_language_from_symbol(symbol_id)

            # Try analyzer DB first (Dart type-resolved)
            if self.analyzer_db and language == "dart":
                resolved = self.analyzer_db.get_resolved_symbol(symbol_id)
                if resolved:
                    steps.append(FlowStep(
                        symbol=symbol_id,
                        filepath=resolved['filepath'],
                        line=resolved['line'],
                        col=resolved['col'],
                        type_name=resolved['type_name'],
                        language="dart"
                    ))
                    continue

            # Try SCIP occurrences (works for all languages)
            if self.repository:
                symbol_info = self.repository.symbols.get_symbol(symbol_id)
                if symbol_info:
                    occs = self.repository.symbols.get_occurrences_for_symbol(symbol_id)
                    if occs:
                        def_occ = next((o for o in occs if o['role'] == 1), occs[0])
                        steps.append(FlowStep(
                            symbol=symbol_id,
                            filepath=def_occ['filepath'],
                            line=def_occ['start_line'],
                            col=def_occ['start_col'],
                            language=language
                        ))
                        continue

            # FFI bridge marker
            if "FFI" in symbol_id.upper() or "ffi" in symbol_id.lower():
                steps.append(FlowStep(
                    symbol=symbol_id,
                    filepath="[FFI Bridge]",
                    line=0,
                    col=0,
                    language="ffi"
                ))

        return steps

    def _detect_language_from_symbol(self, symbol_id: str) -> str:
        """Detect language from symbol ID, filepath, or prefix."""
        # Check explicit prefix (e.g., "dart::my_func", "rust::process")
        if "::" in symbol_id:
            prefix = symbol_id.split("::")[0].lower()
            # Direct language prefix
            if prefix in self.EXTENSION_LANGUAGE_MAP.values():
                return prefix
            if prefix == "dart":
                return "dart"
            if prefix == "rust":
                return "rust"
            # Check if prefix contains a file extension (e.g., "lib/main.dart")
            for ext, lang in self.EXTENSION_LANGUAGE_MAP.items():
                if prefix.endswith(ext):
                    return lang

        # Check file extension anywhere in symbol path
        for ext, lang in self.EXTENSION_LANGUAGE_MAP.items():
            if ext in symbol_id:
                return lang

        # Check for FFI markers
        if "ffi" in symbol_id.lower():
            return "ffi"

        return "unknown"

    def detect_language_from_filepath(self, filepath: str) -> str:
        """Detect language from filepath extension."""
        ext = Path(filepath).suffix.lower()
        return self.EXTENSION_LANGUAGE_MAP.get(ext, "unknown")
