from interface.formatters import format_context_results
from interface.validators import validate_filepaths


def handle_context(filepaths, repository) -> str:
    """Provide a structural index of files. Returns markdown."""
    paths = validate_filepaths(filepaths)
    out_md = []

    for fp in paths:
        symbols = repository.symbols.get_symbols_in_file(fp)
        if not symbols:
            all_files = repository.files.get_all_files_metadata()
            matched = None
            for real_fp in all_files.keys():
                if real_fp.replace("\\", "/").endswith(fp.replace("\\", "/")):
                    matched = real_fp
                    break
            if matched:
                fp = matched
                symbols = repository.symbols.get_symbols_in_file(fp)

        if not symbols:
            out_md.append(
                f"## File Index: `{fp}`\n\n"
                "*No indexed symbols found in file. Make sure the file exists and is indexed.*"
            )
            continue

        occs = repository.symbols.get_occurrences_by_filepath(fp)

        symbol_to_lines = {}
        for sym_name, start_line, end_line, role in occs:
            if sym_name not in symbol_to_lines or role == 1:
                effective_end = end_line if end_line > start_line else start_line
                symbol_to_lines[sym_name] = (start_line, effective_end)

        out_md.append(format_context_results(fp, symbols, symbol_to_lines))

    return "\n\n---\n\n".join(out_md)
