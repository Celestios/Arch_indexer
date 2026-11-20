from typing import List, Union, Any
from interface.formatters import format_lookup_file, format_lookup_symbol
from utils.helpers import demangle_scip_symbol, resolve_symbol_in_repo, is_test_caller


def _get_field(obj: Any, key: str, idx: int, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    if isinstance(obj, (list, tuple)) and len(obj) > idx:
        return obj[idx]
    return default


def _lookup_single(target: str, repository) -> str:
    """Look up details for a single file module or code symbol."""
    target_normalized = target.strip()
    target_slashes = target_normalized.replace(".", "/")

    exact_symbol = resolve_symbol_in_repo(repository, target_normalized)
    matching_symbols = []
    if not exact_symbol:
        raw_matches = repository.graph.search_symbols(target_normalized, 10)
        if not raw_matches:
            raw_matches = repository.graph.search_symbols(target_normalized, 10)
        matching_symbols = [s for s in raw_matches if not str(_get_field(s, "symbol", 0, "")).startswith("local ")]
        if len(matching_symbols) == 1:
            exact_symbol = repository.graph.get_symbol(_get_field(matching_symbols[0], "symbol", 0))
            matching_symbols = []

    exact_file = repository.workspace.get_file(target_normalized)
    if not exact_file:
        exact_file = repository.workspace.get_file(target_normalized.replace("\\", "/"))
    matching_files = []
    if not exact_file:
        matching_files = repository.workspace.search_files(target_slashes, 10)
        if not matching_files:
            matching_files = repository.workspace.search_files(target_normalized, 10)
        if matching_files and len(matching_files) == 1:
            exact_file = repository.workspace.get_file(_get_field(matching_files[0], "filepath", 0))
            matching_files = []

    md = []

    if exact_symbol:
        sym_name = _get_field(exact_symbol, "symbol", 0, "")
        occs_raw = repository.graph.get_occurrences_for_symbol(sym_name)
        occs = [(o["filepath"], o["start_line"], o["end_line"], o["role"]) for o in occs_raw]
        edges = repository.graph.get_edges_for_symbol(sym_name)

        # Batch query filepaths of connected symbols in edges
        other_syms = set()
        for e in edges:
            src = e["source"] if isinstance(e, dict) else e[0]
            tgt = e["target"] if isinstance(e, dict) else e[1]
            if not str(src).startswith("local ") and not str(tgt).startswith("local "):
                if src != sym_name:
                    other_syms.add(src)
                if tgt != sym_name:
                    other_syms.add(tgt)
        sym_fp_map = {}
        if other_syms:
            meta_batch = repository.graph.get_symbols_metadata_batch(list(other_syms))
            sym_fp_map = {s: meta["filepath"] for s, meta in meta_batch.items() if meta.get("filepath")}

        sym_md = format_lookup_symbol(exact_symbol, occs, edges, symbol_filepath_map=sym_fp_map)
        diags = repository.quality.get_diagnostics_for_symbol(sym_name)
        if diags:
            diag_lines = ["\n### Compiler & Analyzer Diagnostics", "| Line:Col | Severity | Code | Message |", "| :--- | :--- | :--- | :--- |"]
            for d in diags:
                code_str = f"`{d['code']}`" if d.get("code") else ""
                diag_lines.append(f"| L{d['line']}:{d['col']} | `{d['severity']}` | {code_str} | {d['message']} |")
            sym_md += "\n" + "\n".join(diag_lines) + "\n"

        # Check for tests transitively covering this symbol
        closure = repository.analytics.get_transitive_closure(sym_name, max_depth=3)
        up_syms = [item["symbol"] for item in closure.get("upstream", [])]
        if up_syms:
            meta_batch = repository.graph.get_symbols_metadata_batch(up_syms)
            tests_found = []
            for s in up_syms:
                meta = meta_batch.get(s, {})
                fp = meta.get("filepath")
                defn = meta.get("definition")
                r = defn.get("role", 0) if defn else 0
                if is_test_caller(s, fp, r):
                    clean_test = demangle_scip_symbol(s)
                    if clean_test not in [t[0] for t in tests_found]:
                        tests_found.append((clean_test, fp))
            if tests_found:
                test_lines = ["\n### Covered By Tests"]
                for ts, tfp in tests_found[:5]:
                    loc_str = f" in `{tfp}`" if tfp else ""
                    test_lines.append(f"- **{ts}**{loc_str}")
                sym_md += "\n" + "\n".join(test_lines) + "\n"

        md.append(sym_md)

    if exact_file:
        file_path = _get_field(exact_file, "filepath", 0, "")
        file_syms = repository.graph.get_symbols_in_file(file_path)
        file_md = format_lookup_file(exact_file, file_syms)
        file_diags = repository.quality.get_diagnostics_for_file(file_path)
        if file_diags:
            diag_lines = ["\n### Compiler & Analyzer Diagnostics", "| Symbol | Line:Col | Severity | Code | Message |", "| :--- | :--- | :--- | :--- | :--- |"]
            for d in file_diags:
                sym_str = f"`{demangle_scip_symbol(d['symbol'])}`" if d.get("symbol") else "-"
                code_str = f"`{d['code']}`" if d.get("code") else ""
                diag_lines.append(f"| {sym_str} | L{d['line']}:{d['col']} | `{d['severity']}` | {code_str} | {d['message']} |")
            file_md += "\n" + "\n".join(diag_lines) + "\n"
        md.append(file_md)

    if not exact_symbol and not exact_file:
        if matching_files:
            md.append("### Matching File Modules Found")
            for f in matching_files:
                f_path = _get_field(f, "filepath", 0, "")
                lang = _get_field(f, "language", 2, "Unknown")
                status = _get_field(f, "status", 4, "Unknown")
                md.append(f"- **{f_path}** (Language: `{lang}`, Status: `{status}`)")
            md.append("")

        if matching_symbols:
            md.append("### Matching Code Symbols Found")
            for s in matching_symbols:
                s_sym = _get_field(s, "symbol", 0, "")
                clean_name = _get_field(s, "clean_symbol", 11) or demangle_scip_symbol(s_sym)
                s_kind = _get_field(s, "kind", 2, "UnspecifiedKind")
                s_fp = _get_field(s, "filepath", 1, "External")
                md.append(f"- **{clean_name}** (`{s_kind}` in `{s_fp or 'External'}`)")
            md.append("")

        if not matching_files and not matching_symbols:
            md.append(f"*No files or symbols matched target query: '{target}'*")

    return "\n".join(md)



def handle_lookup(target: Union[List[str], str], repository) -> str:
    """Look up details for file module(s) or code symbol(s). Returns markdown."""
    if isinstance(target, str):
        targets = [target]
    else:
        targets = list(target)

    results = [_lookup_single(t, repository) for t in targets]
    return "\n\n---\n\n".join(results)
