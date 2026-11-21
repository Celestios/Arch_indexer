import os
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

        symbols = repository.graph.get_symbols_for_files([fp])
        if not symbols:
            all_files = repository.workspace.get_all_files_metadata()
            norm_fp = fp.replace("\\", "/").lower()
            matched = next(
                (
                    real_fp for real_fp in all_files.keys()
                    if norm_fp.endswith(real_fp.replace("\\", "/").lower())
                    or real_fp.replace("\\", "/").lower().endswith(norm_fp)
                ),
                None,
            )
            if matched:
                fp = matched
                symbols = repository.graph.get_symbols_for_files([fp])

        if not symbols:
            out_md.append(
                f"## File Index: `{fp}`\n\n"
                "*No indexed symbols found in file. Make sure the file exists and is indexed.*"
            )
            continue

        symbol_to_lines = {}
        for sym in symbols:
            s_line = sym.get("start_line")
            if s_line is not None:
                e_line = sym.get("end_line") or s_line
                effective_end = e_line if e_line > s_line else s_line
                symbol_to_lines[sym["symbol"]] = (s_line, effective_end)
                symbol_to_lines[demangle_scip_symbol(sym["symbol"])] = (s_line, effective_end)

        res_md = format_context_results(fp, symbols, symbol_to_lines)
        file_diags = repository.quality.get_diagnostics(filepath=fp)
        if file_diags:
            diag_lines = [
                "\n### Compiler & Analyzer Diagnostics",
                "| Symbol | Line:Col | Severity | Code | Message |",
                "| :--- | :--- | :--- | :--- | :--- |",
            ]
            for d in file_diags:
                s_name = demangle_scip_symbol(d["symbol"]) if d.get("symbol") else "-"
                code_str = f"`{d['code']}`" if d.get("code") else ""
                diag_lines.append(f"| `{s_name}` | L{d['line']}:{d['col']} | `{d['severity']}` | {code_str} | {d['message']} |")
            res_md += "\n" + "\n".join(diag_lines) + "\n"

        out_md.append(res_md)

    return "\n\n---\n\n".join(out_md)
