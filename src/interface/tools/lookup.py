from typing import List, Union
from interface.formatters import format_lookup_file, format_lookup_symbol
from utils.helpers import demangle_scip_symbol, resolve_symbol_in_repo, is_test_caller


def _lookup_single(target: str, repository) -> str:
    """Look up details for a single file module or code symbol."""
    target_normalized = target.strip()
    target_slashes = target_normalized.replace(".", "/")

    exact_symbol = resolve_symbol_in_repo(repository, target_normalized)
    matching_symbols = []
    if not exact_symbol:
        raw_matches = repository.graph.search_symbols(target_normalized, 10)
        matching_symbols = [s for s in raw_matches if not str(s.get("symbol", "")).startswith("local ")]
        if len(matching_symbols) == 1:
            exact_symbol = repository.graph.get_symbol(matching_symbols[0]["symbol"])
            matching_symbols = []

    exact_file = repository.workspace.get_file(target_normalized) or repository.workspace.get_file(
        target_normalized.replace("\\", "/")
    )
    matching_files = []
    if not exact_file:
        matching_files = repository.workspace.search_files(target_slashes, 10) or repository.workspace.search_files(
            target_normalized, 10
        )
        if len(matching_files) == 1:
            exact_file = repository.workspace.get_file(matching_files[0]["filepath"])
            matching_files = []

    md = []

    if exact_symbol:
        sym_name = exact_symbol["symbol"]
        focal_fp = (exact_symbol.get("filepath") or "").replace("\\", "/")
        occs = repository.graph.get_occurrences(symbol=sym_name)
        edges = repository.graph.get_edges(symbol=sym_name)

        other_syms = set()
        for e in edges:
            src, tgt = str(e["source"]), str(e["target"])
            if not src.startswith("local ") and not tgt.startswith("local "):
                if src != sym_name:
                    other_syms.add(src)
                if tgt != sym_name:
                    other_syms.add(tgt)

        sym_fp_map = {}
        if other_syms:
            meta_batch = repository.graph.get_symbols_by_ids(list(other_syms))
            sym_fp_map = {s: meta["filepath"] for s, meta in meta_batch.items() if meta.get("filepath")}

        # Keep test callers/references out of the main table; they are listed under Covered By Tests
        filtered_occs = [
            o for o in occs
            if (o.get("filepath") or "").replace("\\", "/") == focal_fp
            or not is_test_caller("", o.get("filepath"), o.get("role", 0))
        ]
        filtered_edges = []
        for e in edges:
            src, tgt = str(e["source"]), str(e["target"])
            other = src if tgt == sym_name else tgt
            if is_test_caller(other, sym_fp_map.get(other)):
                continue
            filtered_edges.append(e)

        sym_md = format_lookup_symbol(exact_symbol, filtered_occs, filtered_edges, symbol_filepath_map=sym_fp_map)
        diags = repository.quality.get_diagnostics(symbol=sym_name)
        if diags:
            diag_lines = [
                "\n### Compiler & Analyzer Diagnostics",
                "| Line:Col | Severity | Code | Message |",
                "| :--- | :--- | :--- | :--- |",
            ]
            for d in diags:
                code_str = f"`{d['code']}`" if d.get("code") else ""
                diag_lines.append(f"| L{d['line']}:{d['col']} | `{d['severity']}` | {code_str} | {d['message']} |")
            sym_md += "\n" + "\n".join(diag_lines) + "\n"

        closure = repository.analytics.get_transitive_closure(sym_name, max_depth=3, direction="upstream")
        up_syms = [item["symbol"] for item in closure.get("upstream", [])]
        if up_syms:
            meta_batch = repository.graph.get_symbols_by_ids(up_syms)
            tests_found = []
            seen_clean = set()
            for s in up_syms:
                fp = meta_batch.get(s, {}).get("filepath")
                if is_test_caller(s, fp):
                    clean_test = demangle_scip_symbol(s)
                    if clean_test not in seen_clean:
                        seen_clean.add(clean_test)
                        tests_found.append((clean_test, fp))
            if tests_found:
                test_lines = ["\n### Covered By Tests"]
                for ts, tfp in tests_found[:5]:
                    loc_str = f" in `{tfp}`" if tfp else ""
                    test_lines.append(f"- **{ts}**{loc_str}")
                sym_md += "\n" + "\n".join(test_lines) + "\n"

        md.append(sym_md)

    if exact_file:
        file_path = exact_file["filepath"]
        file_syms = repository.graph.get_symbols_for_files([file_path])
        file_md = format_lookup_file(exact_file, file_syms)
        file_diags = repository.quality.get_diagnostics(filepath=file_path)
        if file_diags:
            diag_lines = [
                "\n### Compiler & Analyzer Diagnostics",
                "| Symbol | Line:Col | Severity | Code | Message |",
                "| :--- | :--- | :--- | :--- | :--- |",
            ]
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
                md.append(f"- **{f['filepath']}** (Language: `{f.get('language', 'Unknown')}`, Status: `{f.get('status', 'Unknown')}`)")
            md.append("")

        if matching_symbols:
            md.append("### Matching Code Symbols Found")
            for s in matching_symbols:
                clean_name = s.get("clean_symbol") or demangle_scip_symbol(s["symbol"])
                md.append(f"- **{clean_name}** (`{s.get('kind', 'UnspecifiedKind')}` in `{s.get('filepath') or 'External'}`)")
            md.append("")

        if not matching_files and not matching_symbols:
            md.append(f"*No files or symbols matched target query: '{target}'*")

    return "\n".join(md)


def handle_lookup(target: Union[List[str], str], repository) -> str:
    """Look up details for file module(s) or code symbol(s). Returns markdown."""
    targets = [target] if isinstance(target, str) else list(target)
    return "\n\n---\n\n".join(_lookup_single(t, repository) for t in targets)
