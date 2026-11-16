"""
Database Reader Module.
Focused strictly on DuckDB connection lifecycle and SQL queries.
Delegates SCIP and signature parsing to `ScipParser`.
"""

import os
from typing import Dict, List, Any, Optional
import duckdb
from .scip_parser import ScipParser


class DatabaseReader:
    """
    Reads workspace intelligence directly from the DuckDB database.
    """

    def __init__(self, db_path: str = ".arch/arch.db"):
        if not os.path.exists(db_path):
            candidates = [
                db_path,
                os.path.join(".arch", "arch.db"),
                os.path.join("..", ".arch", "arch.db"),
                "arch.db",
            ]
            found = None
            for cand in candidates:
                if os.path.exists(cand):
                    found = cand
                    break
            if not found:
                raise FileNotFoundError(
                    f"Database not found at '{db_path}'. Checked candidates: {candidates}"
                )
            self.db_path = found
        else:
            self.db_path = db_path

        self._conn: Optional[duckdb.DuckDBPyConnection] = None

    def connect(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            self._conn = duckdb.connect(self.db_path, read_only=True)
        return self._conn

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # Backwards-compatible static delegates
    parse_signature_ports = staticmethod(ScipParser.parse_signature_ports)
    parse_scip_symbol = staticmethod(ScipParser.parse_scip_symbol)

    def fetch_files(self) -> List[Dict[str, Any]]:
        conn = self.connect()
        rows = conn.execute("""
            SELECT filepath, language, status, sha256
            FROM files
            ORDER BY filepath
        """).fetchall()

        files = []
        for row in rows:
            filepath = row[0].replace("\\", "/")
            files.append({
                "filepath": filepath,
                "language": row[1] or "python",
                "status": row[2] or "COMPLIANT",
                "sha256": row[3],
                "filename": os.path.basename(filepath),
                "directory": os.path.dirname(filepath) or ".",
            })
        return files

    def fetch_symbols(self) -> List[Dict[str, Any]]:
        conn = self.connect()
        known_files = {
            r[0].replace("\\", "/")
            for r in conn.execute("SELECT filepath FROM files").fetchall()
            if r[0]
        }

        # Check if code_block column exists in symbols table for backward compatibility
        cols = [c[1] for c in conn.execute("PRAGMA table_info('symbols')").fetchall()]
        has_code_col = "code_block" in cols

        query = "SELECT symbol, filepath, kind, signature, docstring, connection_weight"
        if has_code_col:
            query += ", code_block"
        query += " FROM symbols"

        rows = conn.execute(query).fetchall()

        symbols = []
        for row in rows:
            raw_sym = row[0]
            raw_path = row[1]
            filepath = raw_path.replace("\\", "/") if raw_path else None
            kind = row[2] or "Symbol"
            signature = row[3]
            docstring = row[4]
            conn_weight = row[5] or 0
            code_block = row[6] if has_code_col and len(row) > 6 else None

            parsed = ScipParser.parse_scip_symbol(raw_sym, filepath=filepath, known_files=known_files)
            ports = ScipParser.parse_signature_ports(docstring, signature)
            symbols.append({
                "symbol": raw_sym,
                "filepath": filepath,
                "kind": kind,
                "signature": signature,
                "docstring": docstring,
                "connection_weight": conn_weight,
                "label": parsed["label"],
                "display_name": parsed["display_name"],
                "pkg": parsed["pkg"],
                "is_local": parsed["is_local"],
                "is_external": parsed["is_external"],
                "is_parameter": parsed.get("is_parameter", False),
                "ports": ports,
                "code_block": code_block,
            })
        return symbols

    def fetch_symbol_definitions(self) -> Dict[str, Dict[str, Any]]:
        """
        Fetches definition line numbers and locations for symbols from occurrences where (role & 1) != 0.
        Returns a dictionary mapping symbol -> {filepath, start_line, start_col, end_line, end_col}.
        """
        conn = self.connect()
        rows = conn.execute("""
            SELECT symbol, filepath, start_line, start_col, end_line, end_col
            FROM occurrences
            WHERE (role & 1) != 0
        """).fetchall()

        defs: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            sym = r[0]
            raw_path = r[1]
            fp = raw_path.replace("\\", "/") if raw_path else None
            if sym not in defs:
                defs[sym] = {
                    "symbol": sym,
                    "filepath": fp,
                    "start_line": int(r[2]),
                    "start_col": int(r[3]),
                    "end_line": int(r[4]),
                    "end_col": int(r[5]),
                }
        return defs

    def fetch_edges(self) -> List[Dict[str, Any]]:
        conn = self.connect()
        query = """
            SELECT e.source, e.target, e.relation, e.weight,
                   o.start_line, o.start_col
            FROM edges e
            LEFT JOIN symbols s ON e.source = s.symbol
            LEFT JOIN occurrences o ON e.target = o.symbol AND s.filepath = o.filepath
        """
        rows = conn.execute(query).fetchall()

        edges = []
        for row in rows:
            line = int(row[4]) if row[4] is not None else None
            col = int(row[5]) if row[5] is not None else None
            edges.append({
                "source": row[0],
                "target": row[1],
                "relation": row[2] or "Calls",
                "weight": float(row[3]) if row[3] is not None else 1.0,
                "line": line,
                "col": col,
            })
        return edges

    def fetch_occurrences(
        self,
        filepath_filter: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        conn = self.connect()
        query = """
            SELECT symbol, filepath, start_line, start_col, end_line, end_col, role
            FROM occurrences
        """
        params = []
        if filepath_filter:
            query += " WHERE filepath LIKE ? OR filepath LIKE ?"
            p1 = f"%{filepath_filter}%"
            p2 = f"%{filepath_filter.replace('/', chr(92))}%"
            params.extend([p1, p2])

        query += " ORDER BY filepath, start_line, start_col"
        if limit:
            query += f" LIMIT {int(limit)}"

        rows = conn.execute(query, params).fetchall()

        occurrences = []
        for row in rows:
            raw_path = row[1]
            filepath = raw_path.replace("\\", "/") if raw_path else "unknown"
            role = int(row[6])
            occurrences.append({
                "symbol": row[0],
                "filepath": filepath,
                "start_line": int(row[2]),
                "start_col": int(row[3]),
                "end_line": int(row[4]),
                "end_col": int(row[5]),
                "role": role,
                "is_definition": bool(role & 1),
                "is_reference": bool(role & 8),
                "is_import": bool(role & 2),
                "is_write": bool(role & 4),
            })
        return occurrences

    def get_summary_stats(self) -> Dict[str, Any]:
        conn = self.connect()
        files_count = conn.execute("SELECT count(*) FROM files").fetchone()[0]
        symbols_count = conn.execute("SELECT count(*) FROM symbols").fetchone()[0]
        edges_count = conn.execute("SELECT count(*) FROM edges").fetchone()[0]
        occ_count = conn.execute("SELECT count(*) FROM occurrences").fetchone()[0]
        def_count = conn.execute("SELECT count(*) FROM occurrences WHERE (role & 1) != 0").fetchone()[0]
        ref_count = conn.execute("SELECT count(*) FROM occurrences WHERE (role & 8) != 0").fetchone()[0]

        return {
            "files_count": files_count,
            "symbols_count": symbols_count,
            "edges_count": edges_count,
            "occurrences_count": occ_count,
            "definitions_count": def_count,
            "references_count": ref_count,
        }
