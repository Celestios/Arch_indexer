from typing import List, Union
from interface.formatters import format_lookup_file, format_lookup_symbol
from utils.helpers import demangle_scip_symbol, resolve_symbol_in_repo


def _lookup_single(target: str, repository) -> str:
    """Look up details for a single file module or code symbol."""
    target_normalized = target.strip()
    target_slashes = target_normalized.replace(".", "/")

    exact_symbol = resolve_symbol_in_repo(repository, target_normalized)
    matching_symbols = []
    if not exact_symbol:
        raw_matches = repository.symbols.search_symbols_like(target_normalized, 10)
        if not raw_matches:
            raw_matches = repository.symbols.search_symbols_keyword(target_normalized, 10)
        matching_symbols = [s for s in raw_matches if not str(s[0]).startswith("local ")]
        if len(matching_symbols) == 1:
            exact_symbol = repository.symbols.get_symbol_exact(matching_symbols[0][0])
            matching_symbols = []

    exact_file = repository.files.get_file_exact(target_normalized)
    if not exact_file:
        exact_file = repository.files.get_file_exact(target_normalized.replace("\\", "/"))
    matching_files = []
    if not exact_file:
        matching_files = repository.files.search_files_like(target_slashes, 10)
        if not matching_files:
            matching_files = repository.files.search_files_keyword(target_normalized, 10)
        if matching_files and len(matching_files) == 1:
            exact_file = repository.files.get_file_exact(matching_files[0][0])
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
                lang = f[2] if len(f) > 3 else (f[1] if len(f) > 1 else "Unknown")
                status = f[4] if len(f) > 4 else (f[2] if len(f) > 2 else "Unknown")
                md.append(f"- **{f[0]}** (Language: `{lang}`, Status: `{status}`)")
            md.append("")

        if matching_symbols:
            md.append("### Matching Code Symbols Found")
            for s in matching_symbols:
                clean_name = demangle_scip_symbol(s[0])
                md.append(f"- **{clean_name}** (`{s[2]}` in `{s[1] or 'External'}`)")
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
