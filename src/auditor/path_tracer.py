from typing import List
import fnmatch
from db.repository import Repository

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

    def format_path_trace(self, path: List[str]) -> str:
        """Generates a formatted, line-numbered path trace from source to target."""
        trace_lines = []
        for i, sym in enumerate(path):
            symbol_info = self.repository.symbols.get_symbol(sym)
            filepath = symbol_info.get("filepath") if symbol_info else None
            
            line_str = ""
            if filepath:
                if i < len(path) - 1:
                    # Find where it calls the next node
                    next_sym = path[i+1]
                    occs = self.repository.symbols.get_occurrences_for_symbol(next_sym)
                    call_line = None
                    for occ in occs:
                        if occ["filepath"] == filepath:
                            call_line = occ["start_line"]
                            break
                    if call_line is not None:
                        line_str = f":L{call_line}"
                else:
                    # Last node: find its definition line
                    occs = self.repository.symbols.get_occurrences_for_symbol(sym)
                    def_line = None
                    for occ in occs:
                        if occ["filepath"] == filepath and occ["role"] == 1:
                            def_line = occ["start_line"]
                            break
                    if def_line is None and occs:
                        def_line = occs[0]["start_line"]
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
