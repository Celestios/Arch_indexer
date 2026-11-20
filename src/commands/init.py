import sys
import json
from pathlib import Path

from setup.initializer import initialize_workspace
from db.connection import DbConnection
from db.repository import Repository
from engines.scip.wrapper import ScipWrapper
from engines.treesitter import TreesitterEngine
from engines.ffi_linker import FfiLinker
from utils.session import get_project_root

import importlib

# Explicit list of CLI command modules (replaces pkgutil-based discovery in
# the old commands.registry module). Order = order shown in --help.
COMMANDS = [
    "analyze",
    "audit",
    "clear_pending",
    "graph",
    "impact",
    "init",
    "mcp",
    "report",
    "set_fields",
    "set_status",
    "watch",
]


def register_all(subparsers) -> None:
    """Register every CLI subcommand listed in COMMANDS."""
    for module_name in COMMANDS:
        mod = importlib.import_module(f"commands.{module_name}")
        mod.register(subparsers)


def register(subparsers):
    p = subparsers.add_parser("init", help="Initialize workspace and index symbols")
    p.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    p.add_argument("--force", action="store_true", help="Force clean rebuild: delete DB and re-index from scratch")
    p.set_defaults(func=cmd_init)


def _select_languages(languages):
    """Interactively prompt user to select languages to index."""
    selected = []
    if not languages:
        return selected
    if not sys.stdin.isatty():
        return languages
    print("\n--- Language Indexing Options ---")
    print("Select the languages you want to index:")
    for idx, lang in enumerate(languages, 1):
        print(f"  [{idx}] {lang.capitalize()}")
    try:
        choice = input(f"Choose languages [1-{len(languages)}] (comma-separated, e.g., 1,2, default: all): ").strip()
        if choice:
            selected_indices = [int(i.strip()) for i in choice.split(",") if i.strip().isdigit()]
            valid_langs = [languages[i - 1] for i in selected_indices if 1 <= i <= len(languages)]
            if valid_langs:
                return valid_langs
            print("Invalid selection. Defaulting to all detected languages.")
        return languages
    except (KeyboardInterrupt, EOFError):
        print("\nDefaulting to all detected languages.")
        return languages


def _select_include_dirs(project_root, arch_dir, force: bool = False):
    """Interactively prompt user to select directories to index if not configured. Writes selection to config.json."""
    config_path = arch_dir / "config.json"
    existing_config = {}
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                existing_config = json.load(f)
        except Exception:
            existing_config = {}

    # If directories are already defined in config.json and not forcing rebuild, reuse them
    if not force and existing_config:
        configured_dirs = [k.rstrip("/\\") for k, v in existing_config.items() if isinstance(v, dict) and k not in ("exclude", ".")]
        if configured_dirs:
            print(f"Using configured directories from {config_path.name}: {', '.join(configured_dirs)}")
            return configured_dirs

    skip_dirs = {".git", ".arch", ".venv", "__pycache__", "node_modules", ".mypy_cache", ".pytest_cache", "build", "dist"}
    code_exts = {".rs", ".dart", ".py", ".go", ".js", ".ts", ".java"}

    code_dirs = set()
    for ext in code_exts:
        for f in project_root.rglob(f"*{ext}"):
            try:
                rel = f.relative_to(project_root)
            except ValueError:
                continue
            top = rel.parts[0]
            if top not in skip_dirs and not top.startswith("."):
                code_dirs.add(top)

    code_dirs = sorted(code_dirs, key=str.lower)
    if not code_dirs:
        return []

    selected = code_dirs
    if sys.stdin.isatty():
        print("\n--- Directory Indexing Options ---")
        print("Directories containing code files:")
        for idx, d in enumerate(code_dirs, 1):
            print(f"  [{idx}] {d}")
        try:
            choice = input(f"Choose directories [1-{len(code_dirs)}] (comma-separated, e.g., 1,2, default: all): ").strip()
            if choice:
                indices = [int(i.strip()) for i in choice.split(",") if i.strip().isdigit()]
                valid = [code_dirs[i - 1] for i in indices if 1 <= i <= len(code_dirs)]
                if valid:
                    selected = valid
                else:
                    print("Invalid selection. Defaulting to all directories.")
        except (KeyboardInterrupt, EOFError, ValueError):
            print("\nDefaulting to all directories.")

    # Save selection into config.json
    try:
        for d in selected:
            d_key = f"{d}/"
            if d not in existing_config and d_key not in existing_config:
                existing_config[d_key] = {}
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(existing_config, f, indent=2)
    except Exception as e:
        print(f"  Warning: Failed to save directories to config.json: {e}", file=sys.stderr)

    print(f"  Indexed directories: {', '.join(selected)}")
    return selected


def _run_scip_indexer(project_root, repository, selected_languages, force):
    """Run SCIP indexer for selected languages. Returns True if any language was indexed."""
    if not selected_languages:
        return False
    print("\n--- Running Code Graph Indexer ---")
    indexed_any = False
    for lang in selected_languages:
        index_path = ScipWrapper.run_indexer(project_root, lang)
        if index_path:
            print(f"  [{lang}] Index generated at {index_path}")
            parsed = ScipWrapper.parse_index(index_path, project_root)
            ScipWrapper.ingest_index(repository, parsed, project_root=project_root, force=force)
            print(f"  [{lang}] {len(parsed['symbols'])} symbols ingested.")
            indexed_any = True
        else:
            print(f"  [{lang}] Indexing failed. Verify environment settings.", file=sys.stderr)
    return indexed_any


def cmd_init(args):
    """Initialize workspace and index symbols."""
    project_root = get_project_root(args)

    # 1. Workspace init
    if getattr(args, 'force', False):
        arch_dir = project_root / ".arch"
        db_path = arch_dir / "arch.db"
        if db_path.exists():
            print(f"[Force] Deleting database at {db_path}...")
            db_path.unlink()
        for f in arch_dir.glob("index_*.scip"):
            f.unlink()
            print(f"[Force] Deleted {f.name}")

    arch_dir = initialize_workspace(project_root)
    print(f"\nWorkspace folder initialized at {arch_dir}")

    # 2. Auto-recognition
    languages = ScipWrapper.detect_languages(project_root)
    print("\n[Auto-Recognition] System Status:")
    if not languages:
        print("  - Languages: No supported languages detected.")
    else:
        print(f"  - Detected languages: {', '.join(languages)}")
        env_status = ScipWrapper.verify_environment(languages)
        for lang, available in env_status.items():
            status_str = "Available" if available else "NOT found on PATH"
            print(f"    * {lang.capitalize()} Toolchain: {status_str}")

    # 3. User selections
    selected_languages = _select_languages(languages)
    _select_include_dirs(project_root, arch_dir, force=getattr(args, 'force', False))

    # 4. Create shared repository for indexing and linking
    db_conn = DbConnection(arch_dir / "arch.db")
    repository = Repository(db_conn)

    # Sync compliance rules from config.json now that it is configured
    config_path = arch_dir / "config.json"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                conf = json.load(f)
            from setup.initializer import sync_rules_to_db
            sync_rules_to_db(repository, conf)
        except Exception as e:
            print(f"Warning: Failed to sync compliance rules: {e}", file=sys.stderr)

    # 5a. Run Tree-sitter AST Indexer (Stage 1: Declarations, Signatures, Docstrings, Metrics)
    print("\n--- Running Tree-sitter AST Indexer ---")
    from engines.treesitter.loader import TreesitterLoader
    for lang in selected_languages:
        if not TreesitterLoader.get_parser(lang):
            print(f"  Note: Tree-sitter parser for '{lang}' not available; semantic indexing will run via SCIP.")
    try:
        ast_sym_count = TreesitterEngine.sync_project_to_db(repository, project_root, languages=selected_languages)
        print(f"  Tree-sitter: Extracted {ast_sym_count} symbols with exact signatures and docstrings.")
    except Exception as ast_e:
        print(f"  Warning: Tree-sitter extraction encountered an issue: {ast_e}", file=sys.stderr)

    # 5b. Run SCIP Semantic Indexer (Stage 2: Cross-File Graph, Occurrences, Diagnostics)
    indexed_any = _run_scip_indexer(project_root, repository, selected_languages, getattr(args, 'force', False))

    # 6. FFI linking
    if len(selected_languages) > 1 or ("dart" in selected_languages and "rust" in selected_languages):
        print("\n--- Running FFI Bridge Linker ---")
        try:
            linker = FfiLinker(repository)
            edges_created = linker.link_scip_bridges()
            print(f"  Bridge linking complete: {edges_created} cross-language edges created.")
        except Exception as e:
            print(f"  Warning: Bridge linking failed: {e}")

    db_conn.close()

    # 7. Summary
    if selected_languages:
        if indexed_any:
            print("\nIndexing completed successfully!")
        else:
            print("\nIndexing failed. Setup complete, but no symbols were ingested.")
    else:
        print("\nNo languages selected for indexing. Setup complete, but index could not be built.")

    print("\n====================================================")
    print(" Arch setup is complete! Ready to start MCP Server. ")
    print("====================================================")
