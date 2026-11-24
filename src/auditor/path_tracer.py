"""Pure path-tracing, blocklist matching, and canonical symbol-name helpers."""
import fnmatch
from typing import List, Optional, TYPE_CHECKING

from utils.symbol_id import parse_canonical_id

if TYPE_CHECKING:
    from auditor.snapshot import AuditSnapshot


def get_simple_name(symbol: str) -> str:
    """Extracts the leaf symbol name from a canonical symbol ID."""
    if not symbol:
        return ""
    _, _, leaf = parse_canonical_id(symbol)
    return leaf


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


def matches_blocklist(symbol: str, blocklist: List[str], alt_symbols: Optional[List[str]] = None) -> bool:
    """Checks if a canonical external symbol (or its raw scip_id/name) matches any glob in a blocklist."""
    candidates = [symbol]
    if alt_symbols:
        candidates.extend(s for s in alt_symbols if s)

    if symbol.startswith("ext::"):
        pkg_prefix, scope_parts, leaf = parse_canonical_id(symbol)
        # pkg_prefix is 'ext::<mgr>/<pkg>'
        rest = pkg_prefix[5:] if pkg_prefix else ""
        candidates.append(rest)
        if "/" in rest:
            _, pkg = rest.split("/", 1)
            sub_segments = [s for s in (*scope_parts, leaf) if s]
            sub_path = "/".join(sub_segments)
            candidates.append(pkg)
            candidates.append(f"package:{pkg}")
            if sub_path:
                candidates.append(f"{pkg}/{sub_path}")
                candidates.append(f"package:{pkg}/{sub_path}")
            else:
                candidates.append(f"{pkg}/")
                candidates.append(f"package:{pkg}/")

    for s in candidates:
        for pattern in blocklist:
            if fnmatch.fnmatch(s, pattern):
                return True
    return False
