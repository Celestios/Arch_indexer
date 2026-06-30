from pathlib import Path
from typing import Dict, List, Any, Optional
import shutil
from .database import DartAnalyzerDB
from engines.ffi_extractor import FfiSurface

class DartAnalyzerWrapper:
    """
    Drop-in replacement for CodeQlWrapper for Dart language.
    Creates its own database (dart_analyzer_db) similar to CodeQL's codeql_db.

    API parity with CodeQlWrapper:
    - is_available() -> bool
    - create_database(source_root, db_output_dir, language, **kwargs) -> bool
    - run_query(db_dir, ql_file, bqrs_output) -> bool
    - decode_bqrs(bqrs_file, json_output) -> Optional[Dict]
    - trace_data_flow(db_dir, source, sink, language) -> List[Dict]
    """

    def __init__(self, arch_dir: Path):
        self.arch_dir = arch_dir
        self.db = DartAnalyzerDB(arch_dir)
        self._parsed_files: dict = {}

    def is_available(self) -> bool:
        """Check if Dart analyzer package is installed."""
        try:
            from analyzer import PubPackageResolutionContext
            return True
        except ImportError:
            return False

    def create_database(self, source_root: Path, db_output_dir: Path,
                       language: str, **kwargs) -> bool:
        """
        Create analyzer database (like CodeQL's database create).
        db_output_dir is ignored - we use our own dart_analyzer_db.
        """
        if language != "dart":
            return False

        if not self.is_available():
            print("[DartAnalyzer] analyzer package not available, skipping.")
            return False

        print(f"[DartAnalyzer] Creating database at {self.arch_dir / 'dart_analyzer_db'}...")

        # 1. Initialize database
        self.db.initialize()

        # 2. Parse all Dart files
        self._parse_project(source_root)

        # 3. Store parsed results
        for filepath, unit in self._parsed_files.items():
            import hashlib
            content = unit.toString() if hasattr(unit, 'toString') else ''
            content_hash = hashlib.sha256(content.encode()).hexdigest()
            self.db.upsert_parsed_file(filepath, content_hash)

        print("[DartAnalyzer] Database created successfully.")
        return True

    def _parse_project(self, source_root: Path):
        """Parse all Dart files into AST cache."""
        from analyzer import PubPackageResolutionContext

        context = PubPackageResolutionContext()
        dart_files = list(source_root.rglob("*.dart"))

        for f in dart_files:
            try:
                unit = context.parseFile(str(f))
                self._parsed_files[str(f)] = unit
            except Exception as e:
                print(f"[DartAnalyzer] Warning: Failed to parse {f}: {e}")

    def run_query(self, db_dir: Path, ql_file: Path, bqrs_output: Path) -> bool:
        """
        Execute query - translates .ql patterns to analyzer visitors.
        db_dir is ignored - we use our own database.
        Returns True on success, writes BQRS-compatible JSON to bqrs_output.
        """
        ql_content = ql_file.read_text()

        # Determine query type from .ql content
        if "ffi" in ql_content.lower() or "NativeFunction" in ql_content:
            results = self._run_ffi_query()
        else:
            results = []

        # Write results in BQRS-compatible format (list of tuples)
        import json
        bqrs_output.write_text(json.dumps({
            "tuples": [[r] for r in results]
        }))
        return True

    def decode_bqrs(self, bqrs_file: Path, json_output: Path) -> Optional[Dict]:
        """
        Decode BQRS results file to JSON.
        Already JSON for analyzer - just copy and return parsed dict.
        """
        import json
        shutil.copy(bqrs_file, json_output)
        return json.loads(bqrs_file.read_text())

    def trace_data_flow(self, db_dir: Path, source_symbol: str,
                       sink_symbol: str, language: str = "dart") -> List[Dict]:
        """
        Trace data flow between two symbols.
        db_dir is ignored - we use our own database.

        Returns list of dicts matching server.py expected format:
        [{"symbol": str, "filepath": str, "line": int, "col": int, "type": str}]
        """
        from .dataflow import DartDataflowTracer

        tracer = DartDataflowTracer(
            self.arch_dir.parent,  # project_root
            self.db,
            self._get_repository()
        )
        steps = tracer.trace(source_symbol, sink_symbol)

        # Return in exact format server.py expects
        return [{"symbol": s.symbol, "filepath": s.filepath,
                 "line": s.line, "col": s.col, "type": s.type_name}
                for s in steps]

    def detect_ffi(self) -> List[FfiSurface]:
        """
        Detect FFI surfaces using analyzer visitors.
        Returns List[FfiSurface] compatible with FfiMatcher.
        """
        from .ffi_detector import DartFfiDetector

        detector = DartFfiDetector(self.arch_dir.parent, self.db)
        return detector.detect()

    def _run_ffi_query(self) -> List[Dict]:
        """Internal: Run FFI detection and return tuples format."""
        surfaces = self.detect_ffi()
        return [{"value": s.symbol_name} for s in surfaces]

    def _get_repository(self):
        """Get DuckDB repository for SCIP data."""
        try:
            from db.connection import DbConnection
            from db.repository import Repository

            db_path = self.arch_dir / "arch.db"
            if db_path.exists():
                db_conn = DbConnection(db_path)
                return Repository(db_conn)
        except Exception:
            pass
        return None
