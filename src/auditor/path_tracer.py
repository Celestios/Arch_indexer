from typing import List, Optional, TYPE_CHECKING
import fnmatch
from db.repository import Repository
from utils.helpers import find_definition_line

if TYPE_CHECKING:
    from auditor.snapshot import AuditSnapshot

class PathTracer:
    """
    Traces and formats call graph coordinates, checks blocklists, and extracts symbol names.
    """
    def __init__(self, repository: Repository):
        self.repository = repository

    def get_simple_name(self, symbol: str) -> str:
        """Extracts the simple class or function name from a SCIP FQN."""
        sym = symbol.strip()
        for separator in [" ", "::", ".", "/"]:
            if separator in sym:
                sym = sym.split(separator)[-1]
        return sym

    def format_path_trace(self, path: List[str], snapshot: Optional["AuditSnapshot"] = None) -> str:
        """Generates a formatted, line-numbered path trace from source to target."""
        trace_lines = []
        for i, sym in enumerate(path):
            if snapshot is not None:
                symbol_info = snapshot.get_symbol(sym)
            else:
                symbol_info = self.repository.symbols.get_symbol(sym)
            filepath = symbol_info.get("filepath") if symbol_info else None
            
            line_str = ""
            if filepath:
                if i < len(path) - 1:
                    next_sym = path[i+1]
                    if snapshot is not None:
                        occs = snapshot.get_occurrences(next_sym)
                    else:
                        occs = self.repository.symbols.get_occurrences_for_symbol(next_sym)
                    call_line = None
                    for occ in occs:
                        if occ.get("filepath") == filepath:
                            call_line = occ.get("start_line")
                            break
                    if call_line is not None:
                        line_str = f":L{call_line}"
                else:
                    def_line = None
                    if snapshot is not None:
                        def_info = snapshot.definitions_by_symbol.get(sym)
                        if def_info:
                            def_line = def_info.get("start_line")
                    if def_line is None:
                        def_line = find_definition_line(self.repository, sym, filepath)
                    if def_line is not None:
                        line_str = f":L{def_line}"
            
            fp_display = filepath if filepath else "[external]"
            trace_lines.append(f"  {i+1}. {fp_display}{line_str} (symbol: {sym})")
            
        return "\nPath:\n" + "\n".join(trace_lines)

    def matches_blocklist(self, symbol: str, blocklist: List[str]) -> bool:
        """Checks if a symbol matches any pattern in a blocklist."""
        for pattern in blocklist:
            if fnmatch.fnmatch(symbol, pattern):
                return True
        return False
