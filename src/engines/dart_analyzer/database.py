import sqlite3
from pathlib import Path
from typing import Dict, List, Any, Optional
from contextlib import contextmanager

class DartAnalyzerDB:
    """
    Manages the dart_analyzer_db SQLite database.
    Similar role to CodeQL's codeql_db directory.
    """

    def __init__(self, arch_dir: Path):
        self.db_dir = arch_dir / "dart_analyzer_db"
        self.db_path = self.db_dir / "analyzer.db"
        self._conn: Optional[sqlite3.Connection] = None

    def initialize(self):
        """Create database directory and schema."""
        self.db_dir.mkdir(parents=True, exist_ok=True)

        with self.session() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS parsed_files (
                    filepath TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL,
                    parsed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS resolved_symbols (
                    symbol_id TEXT PRIMARY KEY,
                    filepath TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    type_name TEXT,
                    return_type TEXT,
                    parameters TEXT,
                    is_nullable BOOLEAN,
                    line INTEGER NOT NULL,
                    col INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ffi_surfaces (
                    surface_id TEXT PRIMARY KEY,
                    symbol_id TEXT NOT NULL,
                    ffi_type TEXT NOT NULL,
                    native_name TEXT,
                    dart_name TEXT NOT NULL,
                    signature TEXT,
                    filepath TEXT NOT NULL,
                    line INTEGER NOT NULL,
                    FOREIGN KEY (symbol_id) REFERENCES resolved_symbols(symbol_id)
                );

                CREATE TABLE IF NOT EXISTS typed_edges (
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    edge_type TEXT NOT NULL,
                    line INTEGER,
                    FOREIGN KEY (source_id) REFERENCES resolved_symbols(symbol_id),
                    FOREIGN KEY (target_id) REFERENCES resolved_symbols(symbol_id)
                );

                CREATE TABLE IF NOT EXISTS dataflow_facts (
                    fact_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    sink_id TEXT NOT NULL,
                    path_json TEXT NOT NULL,
                    distance INTEGER NOT NULL,
                    computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (source_id) REFERENCES resolved_symbols(symbol_id),
                    FOREIGN KEY (sink_id) REFERENCES resolved_symbols(symbol_id)
                );
            """)

    @contextmanager
    def session(self):
        """Context manager for database sessions."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def is_available(self) -> bool:
        """Check if database exists and has been initialized."""
        return self.db_path.exists()

    def upsert_parsed_file(self, filepath: str, content_hash: str):
        """Record that a file has been parsed."""
        with self.session() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO parsed_files (filepath, content_hash) VALUES (?, ?)",
                (filepath, content_hash)
            )

    def upsert_resolved_symbol(self, symbol_id: str, filepath: str, kind: str,
                               type_name: str, return_type: str, parameters: str,
                               is_nullable: bool, line: int, col: int):
        """Insert or update a type-resolved symbol."""
        with self.session() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO resolved_symbols
                   (symbol_id, filepath, kind, type_name, return_type,
                    parameters, is_nullable, line, col)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (symbol_id, filepath, kind, type_name, return_type,
                 parameters, is_nullable, line, col)
            )

    def upsert_ffi_surface(self, surface_id: str, symbol_id: str, ffi_type: str,
                           native_name: str, dart_name: str, signature: str,
                           filepath: str, line: int):
        """Insert or update an FFI surface."""
        with self.session() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO ffi_surfaces
                   (surface_id, symbol_id, ffi_type, native_name,
                    dart_name, signature, filepath, line)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (surface_id, symbol_id, ffi_type, native_name,
                 dart_name, signature, filepath, line)
            )

    def get_ffi_surfaces(self) -> List[Dict[str, Any]]:
        """Retrieve all FFI surfaces."""
        with self.session() as conn:
            rows = conn.execute("SELECT * FROM ffi_surfaces").fetchall()
            return [dict(r) for r in rows]

    def get_resolved_symbol(self, symbol_id: str) -> Optional[Dict[str, Any]]:
        """Get type-resolved symbol info."""
        with self.session() as conn:
            row = conn.execute(
                "SELECT * FROM resolved_symbols WHERE symbol_id = ?",
                (symbol_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_typed_edges(self, source_id: str) -> List[Dict[str, Any]]:
        """Get outgoing typed edges from a symbol."""
        with self.session() as conn:
            rows = conn.execute(
                "SELECT * FROM typed_edges WHERE source_id = ?",
                (source_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_dataflow_path(self, source_id: str, sink_id: str) -> Optional[List[str]]:
        """Get cached dataflow path between two symbols."""
        with self.session() as conn:
            row = conn.execute(
                "SELECT path_json FROM dataflow_facts WHERE source_id = ? AND sink_id = ?",
                (source_id, sink_id)
            ).fetchone()
            if row:
                import json
                return json.loads(row['path_json'])
            return None

    def cache_dataflow_path(self, source_id: str, sink_id: str,
                            path: List[str], distance: int):
        """Cache a computed dataflow path."""
        import json
        fact_id = f"{source_id}->{sink_id}"
        with self.session() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO dataflow_facts
                   (fact_id, source_id, sink_id, path_json, distance)
                   VALUES (?, ?, ?, ?, ?)""",
                (fact_id, source_id, sink_id, json.dumps(path), distance)
            )
