from contextlib import nullcontext
import logging
from pathlib import Path
from typing import Any, Callable, ContextManager, List, Optional, Union

from auditor.analyzer import Auditor
from engines.sync_pipeline import checkpoint_db, sync_workspace
from setup.initializer import sync_rules_to_db
from utils.helpers import load_config
from utils.symbol_id import canonical_display_name

logger = logging.getLogger(__name__)


def _session(session_factory: Optional[Callable[[], ContextManager[Any]]]):
    return session_factory() if session_factory is not None else nullcontext()


def handle_update(
    repository,
    project_root: Path,
    filepaths: Optional[Union[List[str], str]] = None,
    force: bool = False,
    session_factory: Optional[Callable[[], ContextManager[Any]]] = None,
) -> str:
    """
    Triggers incremental or forced full synchronization of workspace symbols, relationships, and call graph edges.
    Uses the provided repository (and optional scoped session_factory) without opening a second DbConnection.
    """
    arch_dir = project_root / ".arch"
    arch_dir.mkdir(parents=True, exist_ok=True)

    with _session(session_factory):
        try:
            sync_rules_to_db(repository, load_config(project_root))
        except Exception:
            logger.warning("Failed to sync compliance rules from config.json", exc_info=True)

    if force:
        for f in arch_dir.glob("index_*.scip"):
            try:
                f.unlink()
            except OSError:
                pass

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

    sync_res = sync_workspace(
        repository,
        project_root,
        dirty_files=dirty_files,
        force=force,
        run_ffi=True,
        session_factory=session_factory,
    )
    languages = sync_res["languages"]
    if not languages:
        return "## Workspace Update\n\nNo supported languages (Dart, Rust, Go, TypeScript, Java, Python) detected in workspace."

    indexed_langs = sync_res["indexed_languages"]
    failed_langs = sync_res["failed_languages"]
    bridge_edges = sync_res["ffi_edges_created"]

    with _session(session_factory):
        auditor = Auditor(repository, project_root)
        violations = auditor.run_audit()
        checkpoint_db(repository)
        totals = repository.analytics.get_repo_totals()

    md = ["## Workspace Update Complete\n"]
    md.append("*Mode: Full rebuild (`force=True`)*\n" if force else "*Mode: Incremental update*\n")

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
            sym_str = f" (`{canonical_display_name(sym)}`)" if sym else ""
            md.append(f"- **[{v.get('rule_id')}]** `{v.get('filepath')}:{v.get('line')}`{sym_str}: {v.get('message')}")
        if len(violations) > 5:
            md.append(f"- *... and {len(violations) - 5} more.* Run `audit()` for complete details.")
    else:
        md.append("\n**No architectural violations detected.**")

    return "\n".join(md)
