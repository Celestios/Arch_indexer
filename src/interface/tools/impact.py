from typing import Any, Dict, List, Optional, Tuple
from utils.helpers import demangle_scip_symbol, resolve_symbol_in_repo, is_test_caller, detect_entry_point


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
    if sym_record and sym_record.get("kind") in ("Class", "Struct", "Interface", "Trait"):
        return True, sym_record
    if db_symbol.endswith("#"):
        return True, sym_record
    prefix = db_symbol if db_symbol.endswith("#") else db_symbol + "#"
    with repository.symbols.db_conn.session() as conn:
        res = conn.execute(
            """
            SELECT count(*) FROM symbols
            WHERE parent_symbol = ?
               OR (symbol LIKE ? AND (kind IN ('Method', 'Constructor') OR symbol LIKE '%().'))
            """,
            (db_symbol, prefix + "%")
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
        res_md = _handle_class_impact(repository, db_symbol, clean_focal, max_depth)
    else:
        res_md = _handle_symbol_impact(repository, db_symbol, clean_focal, max_depth)

    # Historical Git Co-Change Coupling
    sym_record = repository.symbols.get_symbol(db_symbol)
    focal_fp = sym_record.get("filepath") if sym_record else None
    if focal_fp:
        from change_tracker.git_coupling import GitCouplingMiner
        co_changes = GitCouplingMiner.get_co_changed_files(repository, focal_fp, min_frequency=0.20)
        if co_changes:
            co_md = [
                "### ── Historical Git Co-Change Coupling",
                f"> **Co-Change Warning**: Modifying `{focal_fp}` historically correlates with changes in:"
            ]
            for c in co_changes:
                pct = round(c["frequency"] * 100, 1)
                co_md.append(f"- `{c['filepath']}` ({pct}% co-change over {c['co_change_count']} commits)")
            res_md += "\n" + "\n".join(co_md) + "\n"

    return res_md


def _handle_class_impact(repository, db_symbol: str, clean_focal: str, max_depth: int) -> str:
    prefix = db_symbol if db_symbol.endswith("#") else db_symbol + "#"

    # 1. Fetch member methods
    with repository.symbols.db_conn.session() as conn:
        method_rows = conn.execute(
            """
            SELECT symbol, kind, signature, docstring FROM symbols
            WHERE parent_symbol = ?
               OR (symbol LIKE ? AND symbol LIKE '%().' AND symbol NOT LIKE '%.(%')
            ORDER BY symbol
            """,
            (db_symbol, prefix + "%")
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

    # Check for tests and entry points across all callers
    all_caller_syms = set(seen_sources)
    with repository.edges.db_conn.session() as conn:
        for m_sym in methods_list:
            rows = conn.execute("SELECT source FROM edges WHERE target = ?", (m_sym,)).fetchall()
            for r in rows:
                if not is_noisy_symbol(r[0]) and not r[0].startswith(prefix):
                    all_caller_syms.add(r[0])

    if all_caller_syms:
        meta_callers = repository.symbols.get_symbols_metadata_batch(list(all_caller_syms))
        class_tests = []
        class_roots = []
        for c_sym in all_caller_syms:
            meta = meta_callers.get(c_sym, {})
            fp = meta.get("filepath")
            defn = meta.get("definition")
            r = defn.get("role", 0) if defn else 0
            if is_test_caller(c_sym, fp, r):
                class_tests.append((demangle_scip_symbol(c_sym), fp))
            else:
                inc_count = len(repository.edges.get_incoming_edges(c_sym))
                ep = detect_entry_point(c_sym, fp, inc_count)
                if ep:
                    class_roots.append((demangle_scip_symbol(c_sym), fp, ep))

        if class_tests:
            md.append("### ── Covered By Tests")
            for ts, tfp in sorted(class_tests):
                loc_str = f" in `{tfp}`" if tfp else ""
                md.append(f"- **{ts}**{loc_str}")
            md.append("")

        if class_roots:
            md.append("### ── Root Entry Points Affected")
            for rs, rfp, rep in sorted(class_roots):
                loc_str = f" in `{rfp}`" if rfp else ""
                md.append(f"- **{rs}**{loc_str} [{rep}]")
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

    caller_syms = [item["symbol"] for item in upstream]
    meta_batch = repository.symbols.get_symbols_metadata_batch(caller_syms) if caller_syms else {}

    test_callers = []
    root_entry_points = []
    production_callers = []

    for item in upstream:
        sym = item["symbol"]
        meta = meta_batch.get(sym, {})
        fp = meta.get("filepath")
        defn = meta.get("definition")
        role = defn.get("role", 0) if defn else 0
        if is_test_caller(sym, fp, role):
            test_callers.append((item, fp))
        else:
            production_callers.append((item, fp))
            incoming_edges = repository.edges.get_incoming_edges(sym)
            incoming_count = len(incoming_edges)
            entry_type = detect_entry_point(sym, fp, incoming_count)
            if entry_type:
                root_entry_points.append((item, fp, entry_type))

    md = [f"## Blast Radius for: `{clean_focal}`\n"]

    sym_rec = repository.symbols.get_symbol(db_symbol)
    change_count = sym_rec.get("change_count", 1) if sym_rec else 1
    if change_count >= 3:
        md.append(f"> **Change Risk**: ⚡ High-Churn Hotspot (modified {change_count} times in repository history)\n")
    else:
        md.append(f"> **Stability**: Stable Primitive (low churn: {change_count} edits recorded)\n")

    md.append("### ── Upstream Callers (Who calls this?)")
    if not upstream:
        md.append("*No transitive upstream callers found.*")
    else:
        upstream_sorted = sorted(upstream, key=lambda x: x["depth"])
        for item in upstream_sorted:
            path_nodes = [demangle_scip_symbol(s) for s in item["path"] if not is_noisy_symbol(s)]
            path_str = " ──> ".join(f"`{p}`" for p in path_nodes)
            clean_sym = demangle_scip_symbol(item["symbol"])
            rel_label = f" [{item['relation']}]" if item.get("relation") and item.get("relation") != "Calls" else ""
            md.append(f"- **{clean_sym}** [Depth: {item['depth']}]{rel_label}")
            md.append(f"  * Path: {path_str}")
    md.append("")

    if test_callers:
        md.append("### ── Covered By Tests")
        test_sorted = sorted(test_callers, key=lambda x: x[0]["depth"])
        for item, fp in test_sorted:
            clean_test = demangle_scip_symbol(item["symbol"])
            loc_str = f" in `{fp}`" if fp else ""
            md.append(f"- **{clean_test}**{loc_str} [Depth: {item['depth']}]")
        md.append("")

    if root_entry_points:
        md.append("### ── Root Entry Points Affected")
        root_sorted = sorted(root_entry_points, key=lambda x: x[0]["depth"])
        seen_roots = set()
        for item, fp, entry_type in root_sorted:
            clean_root = demangle_scip_symbol(item["symbol"])
            if clean_root in seen_roots:
                continue
            seen_roots.add(clean_root)
            loc_str = f" in `{fp}`" if fp else ""
            md.append(f"- **{clean_root}**{loc_str} [{entry_type}] [Depth: {item['depth']}]")
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
            rel_label = f" [{item['relation']}]" if item.get("relation") and item.get("relation") != "Calls" else ""
            md.append(f"- **{clean_sym}** [Depth: {item['depth']}]{rel_label}")
            md.append(f"  * Path: {path_str}")
    md.append("")

    return "\n".join(md)

