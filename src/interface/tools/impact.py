from typing import Any, Dict, List, Optional, Tuple
from utils.helpers import demangle_scip_symbol, resolve_symbol_in_repo


def is_noisy_symbol(sym: str) -> bool:
    """Filter out local variables, standard library primitives, typing symbols, and parameter definitions."""
    s = str(sym)
    if s.startswith("local "):
        return True
    if "python-stdlib" in s:
        return True
    if "builtins/" in s or "builtins." in s:
        return True
    if "typing/" in s or "typing." in s:
        return True
    if s.endswith(")") and ".(" in s:
        return True
    return False


def is_class_symbol(repository, db_symbol: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Check if the given symbol represents a Class in the repository."""
    sym_record = repository.symbols.get_symbol(db_symbol)
    if sym_record and sym_record.get("kind") == "Class":
        return True, sym_record
    if db_symbol.endswith("#"):
        return True, sym_record
    prefix = db_symbol if db_symbol.endswith("#") else db_symbol + "#"
    with repository.symbols.db_conn.session() as conn:
        res = conn.execute(
            "SELECT count(*) FROM symbols WHERE symbol LIKE ? AND (kind IN ('Method', 'Constructor') OR symbol LIKE '%().')",
            (prefix + "%",)
        ).fetchone()
        if res and res[0] > 0:
            return True, sym_record
    return False, sym_record


def handle_impact(symbol: str, max_depth: int, repository) -> str:
    """
    Blast radius analysis for a symbol or class.
    For methods/functions: deterministic transitive upstream callers and downstream callees.
    For classes: granular categorization into direct usages (instantiations & type references),
    exposed interface callers, and internal/subsystem downstream dependencies per method.
    """
    resolved = resolve_symbol_in_repo(repository, symbol)
    db_symbol = resolved[0] if resolved else symbol
    clean_focal = demangle_scip_symbol(db_symbol)

    is_cls, _ = is_class_symbol(repository, db_symbol)
    if is_cls:
        return _handle_class_impact(repository, db_symbol, clean_focal, max_depth)
    return _handle_symbol_impact(repository, db_symbol, clean_focal, max_depth)


def _handle_class_impact(repository, db_symbol: str, clean_focal: str, max_depth: int) -> str:
    prefix = db_symbol if db_symbol.endswith("#") else db_symbol + "#"

    # 1. Fetch member methods
    with repository.symbols.db_conn.session() as conn:
        method_rows = conn.execute(
            """
            SELECT symbol, kind, signature, docstring FROM symbols
            WHERE symbol LIKE ? AND symbol LIKE '%().' AND symbol NOT LIKE '%.(%'
            ORDER BY symbol
            """,
            (prefix + "%",)
        ).fetchall()

    methods_list = [r[0] for r in method_rows]
    public_methods = []
    for m in methods_list:
        clean_m = demangle_scip_symbol(m)
        short_name = clean_m.split(".")[-1]
        if not short_name.startswith(("_", "__")):
            public_methods.append(short_name)

    md = [f"## Blast Radius for Class: `{clean_focal}`\n"]

    # Contextual Guidance
    num_methods = len(methods_list)
    if num_methods > 0:
        md.append(
            f"> **Contextual Guidance**: Class `{clean_focal}` has {num_methods} member methods. "
            f"Showing direct usages (instantiations & references), exposed interface callers, and internal dependencies below. "
            f"To see specific blast radius for method edits, run `impact(\"{clean_focal}.<method_name>\")`.\n"
        )
        if public_methods:
            pub_str = ", ".join(f"`{m}`" for m in public_methods)
            md.append(f"**Public Interface**: {pub_str}\n")
    else:
        md.append(f"*No member methods registered for class `{clean_focal}`.*\n")

    # Category 1: Direct Usages (Instantiation & Inheritance & Type References)
    md.append("### ── Direct Usages (Instantiation & Type References)")
    constructor_sym = f"{prefix}__init__()."
    target_symbols = [db_symbol, constructor_sym]

    with repository.edges.db_conn.session() as conn:
        placeholders = ",".join("?" for _ in target_symbols)
        direct_edges = conn.execute(
            f"""
            SELECT source, target, relation FROM edges
            WHERE target IN ({placeholders})
            """,
            target_symbols
        ).fetchall()

    direct_usages = []
    seen_sources = set()
    for src, tgt, rel in direct_edges:
        if is_noisy_symbol(src) or src.startswith(prefix) or src in seen_sources:
            continue
        seen_sources.add(src)
        clean_src = demangle_scip_symbol(src)

        # Tag role
        if tgt == constructor_sym:
            role_tag = "Instantiation"
        elif rel in ("Inherits", "Extends"):
            role_tag = "Inheritance"
        elif src.endswith("."):
            role_tag = "Type Annotation"
        else:
            role_tag = "Direct Call / Reference"
        direct_usages.append((clean_src, role_tag))

    if not direct_usages:
        md.append("*No direct instantiations or type references found.*")
    else:
        for clean_src, role_tag in sorted(direct_usages):
            md.append(f"- **{clean_src}** [{role_tag}]")
            md.append(f"  * Path: `{clean_src}` ──> `{clean_focal}`")
    md.append("")

    # Category 2: Interface Surface (Exposed Callers)
    md.append("### ── Interface Surface (Exposed Callers)")
    method_caller_map = {}
    with repository.edges.db_conn.session() as conn:
        for m_sym in methods_list:
            clean_m = demangle_scip_symbol(m_sym)
            short_m = clean_m.split(".")[-1]
            rows = conn.execute(
                "SELECT source, relation FROM edges WHERE target = ?",
                (m_sym,)
            ).fetchall()
            ext_callers = []
            for src, _ in rows:
                if not is_noisy_symbol(src) and not src.startswith(prefix):
                    clean_caller = demangle_scip_symbol(src)
                    if clean_caller not in ext_callers:
                        ext_callers.append(clean_caller)
            if ext_callers:
                method_caller_map[short_m] = ext_callers

    if not method_caller_map:
        md.append("*No external callers recorded for member methods.*")
    else:
        for m_name, callers in sorted(method_caller_map.items()):
            md.append(f"- **{clean_focal}.{m_name}**:")
            for c in sorted(callers):
                md.append(f"  * Called by `{c}`")
    md.append("")

    # Category 3: Downstream Dependencies (Internal & Subsystem Coupling)
    md.append("### ── Downstream Dependencies (Per Method)")
    deps_found = False
    with repository.edges.db_conn.session() as conn:
        for m_sym in methods_list:
            clean_m = demangle_scip_symbol(m_sym)
            short_m = clean_m.split(".")[-1]
            rows = conn.execute(
                "SELECT target, relation FROM edges WHERE source = ?",
                (m_sym,)
            ).fetchall()
            internal_calls = []
            external_calls = []
            for tgt, _ in rows:
                if is_noisy_symbol(tgt):
                    continue
                clean_tgt = demangle_scip_symbol(tgt)
                if tgt.startswith(prefix):
                    tgt_short = clean_tgt.split(".")[-1]
                    if tgt_short not in internal_calls:
                        internal_calls.append(tgt_short)
                else:
                    if clean_tgt not in external_calls:
                        external_calls.append(clean_tgt)
            if internal_calls or external_calls:
                deps_found = True
                md.append(f"- **{clean_focal}.{short_m}**:")
                if internal_calls:
                    int_str = ", ".join(f"`{c}`" for c in sorted(internal_calls))
                    md.append(f"  * Internal Calls: {int_str}")
                if external_calls:
                    ext_str = ", ".join(f"`{c}`" for c in sorted(external_calls))
                    md.append(f"  * External Subsystems: {ext_str}")

    if not deps_found:
        md.append("*No downstream dependencies recorded.*")
    md.append("")

    return "\n".join(md)


def _handle_symbol_impact(repository, db_symbol: str, clean_focal: str, max_depth: int) -> str:
    closure = repository.edges.get_transitive_closure(db_symbol, max_depth=max_depth)

    raw_upstream = closure.get("upstream", [])
    raw_downstream = closure.get("downstream", [])

    upstream = [item for item in raw_upstream if not is_noisy_symbol(item.get("symbol", ""))]
    downstream = [item for item in raw_downstream if not is_noisy_symbol(item.get("symbol", ""))]

    md = [f"## Blast Radius for: `{clean_focal}`\n"]

    md.append("### ── Upstream Callers (Who calls this?)")
    if not upstream:
        md.append("*No transitive upstream callers found.*")
    else:
        upstream_sorted = sorted(upstream, key=lambda x: x["depth"])
        for item in upstream_sorted:
            path_nodes = [demangle_scip_symbol(s) for s in item["path"] if not is_noisy_symbol(s)]
            path_str = " ──> ".join(f"`{p}`" for p in path_nodes)
            clean_sym = demangle_scip_symbol(item["symbol"])
            md.append(f"- **{clean_sym}** [Depth: {item['depth']}]")
            md.append(f"  * Path: {path_str}")
    md.append("")

    md.append("### ── Downstream Callees (What does this call?)")
    if not downstream:
        md.append("*No transitive downstream callees found.*")
    else:
        downstream_sorted = sorted(downstream, key=lambda x: x["depth"])
        for item in downstream_sorted:
            path_nodes = [demangle_scip_symbol(s) for s in item["path"] if not is_noisy_symbol(s)]
            path_str = " ──> ".join(f"`{p}`" for p in path_nodes)
            clean_sym = demangle_scip_symbol(item["symbol"])
            md.append(f"- **{clean_sym}** [Depth: {item['depth']}]")
            md.append(f"  * Path: {path_str}")
    md.append("")

    return "\n".join(md)

