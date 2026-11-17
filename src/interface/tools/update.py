import json
from pathlib import Path
from typing import Any, List, Optional, Union

from setup.initializer import initialize_workspace, sync_rules_to_db
from engines.scip_wrapper import ScipWrapper
from engines.treesitter import TreesitterEngine
from auditor.analyzer import Auditor
from utils.helpers import demangle_scip_symbol


def handle_update(
    repository,
    project_root: Path,
    filepaths: Optional[Union[List[str], str]] = None,
    force: bool = False,
) -> str:
    """
    Triggers incremental or forced full synchronization of workspace symbols, relationships, and call graph edges.
    Note that the MCP watcher module already auto-updates the database in the background (tree-sitter updates are quick, while SCIP-gathered info might lag). Use this tool only for manual updates when forced synchronization or explicit re-indexing is required.
    """
    arch_dir = initialize_workspace(project_root)

    # Sync compliance rules from config.json if configured
    config_path = arch_dir / "config.json"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                conf = json.load(f)
            sync_rules_to_db(repository, conf)
        except Exception:
            pass

    # Optional force cleanup of old SCIP artifacts
    if force:
        for f in arch_dir.glob("index_*.scip"):
            try:
                f.unlink()
            except Exception:
                pass

    # Process and normalize target filepaths if specified
    dirty_files = None
    if filepaths:
        if isinstance(filepaths, str):
            fps = [p.strip() for p in filepaths.split(",") if p.strip()]
        else:
            fps = list(filepaths)
        dirty_files = set()
        for fp in fps:
            try:
                p = Path(fp)
                if p.is_absolute():
                    rel = str(p.resolve().relative_to(project_root.resolve())).replace("\\", "/")
                else:
                    rel = str(p).replace("\\", "/")
            except ValueError:
                rel = str(fp).replace("\\", "/")
            dirty_files.add(rel)

    languages = ScipWrapper.detect_languages(project_root)
    if not languages:
        return "## Workspace Update\n\nNo supported languages (Dart, Rust, Go, TypeScript, Java, Python) detected in workspace."

    # Stage 1: Fast Tree-sitter AST Sync (Exact signatures, docstrings, metrics)
    try:
        TreesitterEngine.sync_project_to_db(repository, project_root, filepaths=dirty_files, languages=languages)
    except Exception:
        pass

    indexed_langs = []
    failed_langs = []
    for lang in languages:
        index_path = ScipWrapper.run_indexer(project_root, lang)
        if index_path:
            parsed = ScipWrapper.parse_index(index_path, project_root, changed_files=dirty_files)
            ScipWrapper.ingest_index(repository, parsed, project_root=project_root, force=force)
            indexed_langs.append(lang)
        else:
            failed_langs.append(lang)

    bridge_edges = 0
    if len(languages) > 1 or ("dart" in languages and "rust" in languages):
        try:
            from engines.ffi_linker import FfiLinker
            linker = FfiLinker(repository)
            bridge_edges = linker.link_scip_bridges() or 0
        except Exception:
            pass

    # Run compliance audit check
    auditor = Auditor(repository, project_root)
    violations = auditor.run_audit()

    totals = repository.metrics.get_repo_totals()

    md = ["## Workspace Update Complete\n"]
    if force:
        md.append("*Mode: Full rebuild (`force=True`)*\n")
    else:
        md.append("*Mode: Incremental update*\n")

    if dirty_files:
        md.append(f"- **Target Files ({len(dirty_files)})**: {', '.join(sorted(dirty_files)[:5])}{' ...' if len(dirty_files) > 5 else ''}")

    md.append(f"- **Languages Detected**: {', '.join(languages)}")
    if indexed_langs:
        md.append(f"- **Languages Successfully Indexed**: {', '.join(indexed_langs)}")
    if failed_langs:
        md.append(f"- **Languages Skipped/Failed**: {', '.join(failed_langs)} (toolchain CLI not on PATH)")

    md.append(f"- **Files Indexed**: {totals.get('files', 0)}")
    md.append(f"- **Symbols Registered**: {totals.get('symbols', 0)}")
    md.append(f"- **Dependencies (Call Graph Edges)**: {totals.get('edges', 0)}")
    if bridge_edges:
        md.append(f"- **Cross-Language FFI Bridges**: {bridge_edges}")
    md.append(f"- **Active Architectural Violations**: {totals.get('violations', 0)}")

    if violations:
        md.append(f"\n### Active Violations Found ({len(violations)}):")
        for v in violations[:5]:
            sym = v.get("symbol")
            sym_str = f" (`{demangle_scip_symbol(sym)}`)" if sym else ""
            md.append(f"- **[{v.get('rule_id')}]** `{v.get('filepath')}:{v.get('line')}`{sym_str}: {v.get('message')}")
        if len(violations) > 5:
            md.append(f"- *... and {len(violations) - 5} more.* Run `audit()` for complete details.")
    else:
        md.append("\n**No architectural violations detected.**")

    return "\n".join(md)
