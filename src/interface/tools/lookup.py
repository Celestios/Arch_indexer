from interface.formatters import format_lookup_file, format_lookup_symbol


def handle_lookup(target: str, repository) -> str:
    """Look up details for a file module or code symbol. Returns markdown."""
    target_normalized = target.strip()
    target_slashes = target_normalized.replace(".", "/")

    exact_symbol = None
    matching_symbols = []
    exact_file = None
    matching_files = []

    exact_symbol = repository.symbols.get_symbol_exact(target_normalized)
    if not exact_symbol:
        matching_symbols = repository.symbols.search_symbols_like(target_normalized, 10)

    exact_file = repository.files.get_file_exact(target_normalized)
    if not exact_file:
        exact_file = repository.files.get_file_exact(target_normalized.replace("\\", "/"))
    if not exact_file:
        matching_files = repository.files.search_files_like(target_slashes, 10)
        if matching_files and len(matching_files) == 1:
            exact_file = matching_files[0]
            matching_files = []

    md = []

    if exact_symbol:
        occs_raw = repository.symbols.get_occurrences_for_symbol(exact_symbol[0])
        occs = [(o["filepath"], o["start_line"], o["end_line"], o["role"]) for o in occs_raw]
        edges = repository.symbols.get_edges_for_symbol(exact_symbol[0])
        md.append(format_lookup_symbol(exact_symbol, occs, edges))

    if exact_file:
        file_syms = repository.symbols.get_symbols_by_filepath_exact(exact_file[0])
        md.append(format_lookup_file(exact_file, file_syms))

    if not exact_symbol and not exact_file:
        if matching_files:
            md.append("### Matching File Modules Found")
            for f in matching_files:
                md.append(f"- **{f[0]}** (Language: `{f[2]}`, Status: `{f[4]}`)")
            md.append("")

        if matching_symbols:
            md.append("### Matching Code Symbols Found")
            for s in matching_symbols:
                md.append(f"- **{s[0]}** (`{s[2]}` in `{s[1] or 'External'}`)")
            md.append("")

        if not matching_files and not matching_symbols:
            md.append(f"*No files or symbols matched target query: '{target}'*")

    return "\n".join(md)
