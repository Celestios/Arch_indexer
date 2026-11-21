"""Pure path-tracing, blocklist matching, and symbol-name formatting helpers."""
import fnmatch
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from auditor.snapshot import AuditSnapshot


def get_simple_name(symbol: str) -> str:
    """Extracts the simple class or function name from a SCIP FQN."""
    sym = symbol.strip()
    for separator in (" ", "::", ".", "/"):
        if separator in sym:
            sym = sym.split(separator)[-1]
    return sym


def format_path_trace(path: List[str], snapshot: Optional["AuditSnapshot"] = None) -> str:
    """Generates a formatted, line-numbered path trace from source to target using AuditSnapshot."""
    trace_lines = []
    for i, sym in enumerate(path):
        symbol_info = snapshot.get_symbol(sym) if snapshot is not None else None
        filepath = symbol_info.get("filepath") if symbol_info else None
        line_str = ""
        if filepath and snapshot is not None:
            if i < len(path) - 1:
                next_sym = path[i + 1]
                call_line = None
                for edge in snapshot.get_incoming(next_sym):
                    if edge.get("source") == sym and edge.get("call_line"):
                        call_line = edge.get("call_line")
                        break
                if call_line is None:
                    def_info = snapshot.get_definition(sym)
                    call_line = symbol_info.get("start_line") or (def_info.get("start_line") if def_info else None)
                if call_line is not None:
                    line_str = f":L{call_line}"
            else:
                def_info = snapshot.get_definition(sym)
                def_line = def_info.get("start_line") if def_info else symbol_info.get("start_line")
                if def_line is not None:
                    line_str = f":L{def_line}"

        fp_display = filepath if filepath else "[external]"
        trace_lines.append(f"  {i + 1}. {fp_display}{line_str} (symbol: {sym})")

    return "\nPath:\n" + "\n".join(trace_lines)


def matches_blocklist(symbol: str, blocklist: List[str]) -> bool:
    """Checks if a symbol matches any pattern in a blocklist."""
    for pattern in blocklist:
        if fnmatch.fnmatch(symbol, pattern):
            return True
    return False
