def handle_trace(source, sink, repository, arch_dir, get_bin_dir_fn) -> str:
    """Trace data flow from source to sink. Returns markdown."""
    from engines.dart_analyzer import CombinedDataflowTracer, DartAnalyzerDB
    from engines.codeql_wrapper import CodeQlWrapper

    analyzer_db = None
    dart_db_path = arch_dir / "dart_analyzer_db"
    if dart_db_path.exists():
        analyzer_db = DartAnalyzerDB(arch_dir)

    codeql_wrappers = {}
    try:
        bin_dir = get_bin_dir_fn()
        for db_entry in arch_dir.iterdir():
            if db_entry.is_dir() and db_entry.name.startswith("codeql_db"):
                lang = db_entry.name.replace("codeql_db_", "").replace("codeql_db", "")
                if not lang:
                    lang = "generic"
                try:
                    codeql = CodeQlWrapper(bin_dir)
                    if codeql.is_available():
                        codeql_wrappers[lang] = codeql
                except Exception:
                    pass
    except Exception:
        pass

    tracer = CombinedDataflowTracer(
        project_root=arch_dir.parent,
        arch_dir=arch_dir,
        analyzer_db=analyzer_db,
        codeql_wrappers=codeql_wrappers,
        repository=repository,
    )
    steps = tracer.trace(source, sink)

    if not steps:
        return f"## Data Flow Trace\n\nNo flow path found between source `{source}` and sink `{sink}`."

    md = [f"## Data Flow Trace: Path Found ({len(steps)} steps)\n"]
    for i, step in enumerate(steps, 1):
        lang_tag = f" [{step.language}]" if step.language and step.language != "unknown" else ""
        md.append(f"{i}. `{step.symbol}` (`{step.filepath}:L{step.line}`){lang_tag}")
    md.append("")

    return "\n".join(md)
