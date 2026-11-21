"""Database Reader Module delegating cleanly to domain stores."""

import os
from pathlib import Path
from typing import Dict, List, Any, Optional

from db.connection import DbConnection
from db.repository import Repository
from .scip_parser import parse_scip_symbol, parse_signature_ports


class DatabaseReader:
    """Reads workspace intelligence from DuckDB via Repository domain stores."""

    def __init__(
        self,
        db_path: str = ".arch/arch.db",
        repository: Optional[Repository] = None,
        db_conn: Optional[DbConnection] = None,
    ):
        if repository is not None:
            self.repository = repository
            self.db_conn = db_conn
            self.db_path = str(db_path)
            self._own_conn = False
        elif db_conn is not None:
            self.db_conn = db_conn
            self.db_path = str(self.db_conn.db_path)
            self.repository = Repository(self.db_conn)
            self._own_conn = False
        else:
            if not os.path.exists(db_path):
                candidates = [
                    db_path,
                    os.path.join(".arch", "arch.db"),
                    os.path.join("..", ".arch", "arch.db"),
                    "arch.db",
                ]
                found = next((cand for cand in candidates if os.path.exists(cand)), None)
                if not found:
                    raise FileNotFoundError(
                        f"Database not found at '{db_path}'. Checked candidates: {candidates}"
                    )
                self.db_path = found
            else:
                self.db_path = db_path

            self.db_conn = DbConnection(Path(self.db_path))
            self.repository = Repository(self.db_conn)
            self._own_conn = True

    def close(self):
        """Closes the connection if owned by this instance."""
        if getattr(self, "_own_conn", False) and self.db_conn is not None:
            self.db_conn.close()

    def __enter__(self):
        if self.db_conn is not None:
            self.db_conn.get_connection()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def fetch_files(self) -> List[Dict[str, Any]]:
        """Fetches all tracked files using WorkspaceStore."""
        return [
            {
                "filepath": f["filepath"],
                "language": f.get("language") or "python",
                "status": f.get("status") or "COMPLIANT",
                "sha256": f.get("sha256"),
                "filename": os.path.basename(f["filepath"]),
                "directory": os.path.dirname(f["filepath"]) or ".",
            }
            for f in self.repository.workspace.get_all_files()
        ]

    def fetch_symbols(self) -> List[Dict[str, Any]]:
        """Fetches all symbols using GraphStore and enriches them with parsed ports/labels."""
        known_files = {f["filepath"] for f in self.repository.workspace.get_all_files() if f.get("filepath")}
        symbols = []
        for sym in self.repository.graph.get_all_symbols():
            raw_sym = sym["symbol"]
            filepath = sym.get("filepath")
            signature = sym.get("signature")
            docstring = sym.get("docstring")
            clean_sym = sym.get("clean_symbol")

            parsed = parse_scip_symbol(raw_sym, filepath=filepath, known_files=known_files, clean_symbol=clean_sym)
            ports = parse_signature_ports(docstring, signature)
            symbols.append({
                "symbol": raw_sym,
                "clean_symbol": clean_sym,
                "filepath": filepath,
                "kind": sym.get("kind") or "Symbol",
                "signature": signature,
                "docstring": docstring,
                "connection_weight": sym.get("connection_weight") or 0,
                "start_line": sym.get("start_line"),
                "start_col": sym.get("start_col"),
                "end_line": sym.get("end_line"),
                "end_col": sym.get("end_col"),
                "label": parsed["label"],
                "display_name": parsed["display_name"],
                "pkg": parsed["pkg"],
                "is_local": parsed["is_local"],
                "is_external": parsed["is_external"],
                "is_parameter": parsed.get("is_parameter", False),
                "ports": ports,
            })
        return symbols

    def fetch_symbol_definitions(self) -> Dict[str, Dict[str, Any]]:
        """Projects symbol definition coordinates directly from symbols table."""
        defs: Dict[str, Dict[str, Any]] = {}
        for sym in self.repository.graph.get_all_symbols():
            if sym.get("start_line") is not None:
                sid = sym["symbol"]
                defs[sid] = {
                    "symbol": sid,
                    "filepath": sym.get("filepath"),
                    "start_line": int(sym["start_line"]),
                    "start_col": int(sym["start_col"]) if sym.get("start_col") is not None else 0,
                    "end_line": int(sym["end_line"]) if sym.get("end_line") is not None else int(sym["start_line"]),
                    "end_col": int(sym["end_col"]) if sym.get("end_col") is not None else 0,
                }
        return defs

    def fetch_edges(self) -> List[Dict[str, Any]]:
        """Fetches edges with call line locations."""
        return [
            {
                "source": row["source"],
                "target": row["target"],
                "relation": row.get("relation") or "Calls",
                "weight": float(row.get("weight", 1.0)) if row.get("weight") is not None else 1.0,
                "line": int(row["line"]) if row.get("line") is not None else None,
                "col": int(row["col"]) if row.get("col") is not None else None,
            }
            for row in self.repository.graph.get_edges_with_locations()
        ]

    def fetch_occurrences(
        self,
        filepath_filter: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Fetches occurrences matching optional filepath filter."""
        raw_occs = self.repository.graph.get_occurrences(filepath_filter=filepath_filter, limit=limit)
        return [
            {
                "symbol": row["symbol"],
                "filepath": row.get("filepath") or "unknown",
                "start_line": int(row["start_line"]),
                "start_col": int(row["start_col"]),
                "end_line": int(row["end_line"]),
                "end_col": int(row["end_col"]),
                "role": int(row["role"]),
                "is_definition": bool(int(row["role"]) & 1),
                "is_reference": bool(int(row["role"]) & 8),
                "is_import": bool(int(row["role"]) & 2),
                "is_write": bool(int(row["role"]) & 4),
            }
            for row in raw_occs
        ]

    def get_summary_stats(self) -> Dict[str, Any]:
        """Returns workspace summary statistics from AnalyticsStore."""
        return self.repository.analytics.get_graph_snapshot_data()
