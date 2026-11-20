import os
from pathlib import Path
from interface.formatters import format_context_results
from interface.validators import validate_filepaths
from utils.helpers import demangle_scip_symbol


def handle_context(filepaths, repository, project_root=None) -> str:
    """Provide a structural index of files. Returns markdown."""
    paths = validate_filepaths(filepaths)
    out_md = []

    for fp in paths:
        if project_root and os.path.isabs(fp):
            try:
                rel = os.path.relpath(fp, project_root).replace("\\", "/")
                if not rel.startswith(".."):
                    fp = rel
            except Exception:
                pass

        symbols = repository.graph.get_symbols_in_file(fp)
        if not symbols:
            all_files = repository.workspace.get_all_files_metadata()
            matched = None
            norm_fp = fp.replace("\\", "/").lower()
            for real_fp in all_files.keys():
                norm_real = real_fp.replace("\\", "/").lower()
                if norm_fp.endswith(norm_real) or norm_real.endswith(norm_fp):
                    matched = real_fp
                    break
            if matched:
                fp = matched
                symbols = repository.graph.get_symbols_in_file(fp)

        if not symbols:
            out_md.append(
                f"## File Index: `{fp}`\n\n"
                "*No indexed symbols found in file. Make sure the file exists and is indexed.*"
            )
            continue

        occs = repository.graph.get_occurrences_for_file(fp)

        symbol_to_lines = {}
        for occ in occs:
            sym_name = occ["symbol"] if isinstance(occ, dict) else occ[0]
            start_line = occ["start_line"] if isinstance(occ, dict) else occ[1]
            end_line = occ["end_line"] if isinstance(occ, dict) else occ[2]
            role = occ["role"] if isinstance(occ, dict) else occ[3]
            if sym_name not in symbol_to_lines or role == 1:
                effective_end = end_line if end_line > start_line else start_line
                symbol_to_lines[sym_name] = (start_line, effective_end)
                symbol_to_lines[demangle_scip_symbol(sym_name)] = (start_line, effective_end)

        res_md = format_context_results(fp, symbols, symbol_to_lines)
        file_diags = repository.quality.get_diagnostics_for_file(fp)
        if file_diags:
            diag_lines = ["\n### Compiler & Analyzer Diagnostics", "| Symbol | Line:Col | Severity | Code | Message |", "| :--- | :--- | :--- | :--- | :--- |"]
            for d in file_diags:
                s_name = demangle_scip_symbol(d['symbol']) if d.get('symbol') else "-"
                code_str = f"`{d['code']}`" if d.get("code") else ""
                diag_lines.append(f"| `{s_name}` | L{d['line']}:{d['col']} | `{d['severity']}` | {code_str} | {d['message']} |")
            res_md += "\n" + "\n".join(diag_lines) + "\n"

        out_md.append(res_md)

    return "\n\n---\n\n".join(out_md)
