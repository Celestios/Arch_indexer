from typing import List, Union

from interface.formatters import format_query_results


def handle_query(
    text: Union[List[str], str],
    limit: int,
    repository,
    embedder,
) -> str:
    """Run keyword and semantic searches over the codebase. Returns markdown."""
    queries = [text] if isinstance(text, str) else text

    md = []
    for q in queries:
        keyword_symbols = repository.symbols.search_symbols_keyword(q, limit)
        file_matches = repository.files.search_files_keyword(q, limit)

        results = []
        try:
            embedding = embedder.embed(q)
            results = repository.symbols.semantic_search(embedding, limit=limit)
        except Exception:
            pass

        md.append(format_query_results(q, keyword_symbols, file_matches, results))

    return "\n".join(md)
