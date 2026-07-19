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
    - decode_results(bqrs_file, json_output) -> Optional[Dict]
    - decode_bqrs(bqrs_file, json_output) -> Optional[Dict]  (alias for decode_results)
    - extract_kinds(db_dir, language) -> List[Dict[str, Any]]
    - trace_data_flow(db_dir, source, sink, language) -> List[Dict]
    """

    def __init__(self, arch_dir: Path):
        self.arch_dir = arch_dir
        self.db = DartAnalyzerDB(arch_dir)
        self._parsed_files: dict = {}

    def is_available(self) -> bool:
        """Check if the Dart SDK is available on the system PATH."""
        return shutil.which("dart") is not None

    def create_database(self, source_root: Path, db_output_dir: Path,
                       language: str, **kwargs) -> bool:
        """
        Create analyzer database (like CodeQL's database create).

        db_output_dir is intentionally ignored. Unlike CodeQlWrapper which
        stores its database at the caller-specified location, DartAnalyzer
        uses a fixed internal database at ``self.arch_dir / 'dart_analyzer_db'``.
        This is a deliberate design choice to keep the Dart analyzer's
        self-contained database lifecycle separate from the caller.
        """
        if language != "dart":
            return False

        print(f"[DartAnalyzer] Creating database at {self.arch_dir / 'dart_analyzer_db'}...")

        # 1. Initialize database
        self.db.initialize()

        # 2. Parse all Dart files (incremental)
        force = kwargs.get("force", False)
        self._parse_project(source_root, force=force)

        print("[DartAnalyzer] Database created successfully.")
        return True

    def _make_surface_id(self, filepath: str, name: str) -> str:
        """Generate unique surface ID."""
        from .graph_utils import make_surface_id
        return make_surface_id(filepath, name)

    def _parse_project(self, source_root: Path, force: bool = False):
        """Parse all Dart files and extract FFI surfaces using Dart SDK Analyzer."""
        import subprocess
        import shutil
        import json
        import sys

        # Skip if no Dart files exist outside the helper directory
        dart_files = [f for f in source_root.rglob("*.dart")
                      if "dart_analyzer" not in str(f) and ".dart_tool" not in str(f)]
        if not dart_files:
            print("[DartAnalyzer] No Dart files found in project, skipping.")
            return

        # 1. Locate the helper template directory
        if getattr(sys, 'frozen', False):
            template_dir = Path(sys._MEIPASS) / "engines" / "dart_analyzer" / "helper"
        else:
            template_dir = Path(__file__).resolve().parent / "helper"

        # 2. Define writeable helper directory in workspace
        workspace_helper = self.arch_dir / "dart_analyzer_helper"

        # Copy helper files unconditionally to keep them in sync with the templates
        workspace_helper.mkdir(parents=True, exist_ok=True)
        shutil.copy(template_dir / "pubspec.yaml", workspace_helper / "pubspec.yaml")
        (workspace_helper / "bin").mkdir(parents=True, exist_ok=True)
        shutil.copy(template_dir / "bin" / "analyze.dart", workspace_helper / "bin" / "analyze.dart")

        # 3. Run dart pub get if not resolved
        pkg_config = workspace_helper / ".dart_tool" / "package_config.json"
        if not pkg_config.exists():
            print("[DartAnalyzer] Resolving analyzer package dependencies...")
            subprocess.run(
                ["dart", "pub", "get"],
                cwd=str(workspace_helper),
                shell=(sys.platform == "win32"),
                capture_output=True,
                check=True
            )

        # 4. Run Dart Analyzer tool via subprocess
        output_json = self.arch_dir / "dart_analyzer_results.json"
        if output_json.exists():
            output_json.unlink()

        print("[DartAnalyzer] Running Dart SDK Analyzer on project...")
        res = subprocess.run(
            ["dart", "run", "bin/analyze.dart", str(source_root), str(output_json)],
            cwd=str(workspace_helper),
            shell=(sys.platform == "win32"),
            capture_output=True,
            text=True
        )

        if res.returncode != 0:
            print(f"[DartAnalyzer] Error running analyzer: {res.stderr}", file=sys.stderr)
            return

        if not output_json.exists():
            print("[DartAnalyzer] Error: Analyzer output JSON not generated.", file=sys.stderr)
            return

        # 5. Load JSON results into database
        with open(output_json, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Clear old database tables
        with self.db.session() as conn:
            conn.execute("DELETE FROM resolved_symbols")
            conn.execute("DELETE FROM ffi_surfaces")
            conn.execute("DELETE FROM typed_edges")
            conn.execute("DELETE FROM dataflow_facts")
            conn.execute("DELETE FROM parsed_files")

        # Insert resolved symbols
        for sym in data.get('symbols', []):
            self.db.upsert_resolved_symbol(
                symbol_id=sym['symbol_id'],
                filepath=sym['filepath'],
                kind=sym['kind'],
                type_name=sym['type_name'],
                return_type=None,
                parameters=None,
                is_nullable=False,
                line=sym['line'],
                col=sym['col']
            )

        # Insert FFI surfaces
        for ffi in data.get('ffi_surfaces', []):
            self.db.upsert_ffi_surface(
                surface_id=self._make_surface_id(ffi['filepath'], ffi['dart_name']),
                symbol_id=ffi['symbol_id'],
                ffi_type=ffi['ffi_type'],
                native_name=ffi['native_name'],
                dart_name=ffi['dart_name'],
                signature=ffi['signature'],
                filepath=ffi['filepath'],
                line=ffi['line']
            )

        # Insert typed edges (calls, assigns, etc.)
        with self.db.session() as conn:
            for edge in data.get('edges', []):
                conn.execute(
                    "INSERT INTO typed_edges (source_id, target_id, edge_type, line) VALUES (?, ?, ?, ?)",
                    (edge['source'], edge['target'], edge['relation'], edge['line'])
                )

        # Clean up output JSON
        if output_json.exists():
            output_json.unlink()

    def run_query(self, db_dir: Path, ql_file: Path, bqrs_output: Path) -> bool:
        """
        Execute query - translates .ql patterns to analyzer visitors.

        db_dir is intentionally ignored. DartAnalyzer queries its own
        internal database (``self.arch_dir / 'dart_analyzer_db'``) and does
        not use the caller-provided db_dir.

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

    def decode_results(self, bqrs_file: Path, json_output: Path) -> Optional[Dict]:
        """
        Decode results file to JSON.

        For DartAnalyzer, the input is already JSON (not binary BQRS as
        used by CodeQlWrapper). The file is copied as-is and parsed.
        """
        import json
        shutil.copy(bqrs_file, json_output)
        return json.loads(bqrs_file.read_text())

    def decode_bqrs(self, bqrs_file: Path, json_output: Path) -> Optional[Dict]:
        """Alias for decode_results() — maintained for API compatibility with CodeQlWrapper."""
        return self.decode_results(bqrs_file, json_output)

    def extract_kinds(self, db_dir: Path, language: str) -> List[Dict[str, Any]]:
        """
        Extract kind information for symbols in the database.

        db_dir is intentionally ignored — uses the DartAnalyzer's own database.

        Returns list of dicts with keys: name, kind, file, line
        """
        if language != "dart":
            return []
        try:
            with self.db.session() as conn:
                rows = conn.execute(
                    "SELECT symbol_id, kind, filepath, line FROM resolved_symbols"
                ).fetchall()
                return [
                    {"name": r[0], "kind": r[1], "file": r[2], "line": r[3]}
                    for r in rows
                ]
        except Exception:
            return []

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
