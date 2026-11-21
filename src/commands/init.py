import sys
import json
from pathlib import Path

from setup.initializer import initialize_workspace
from db.connection import DbConnection
from db.repository import Repository
from engines.scip.wrapper import detect_languages, verify_environment
from engines.sync_pipeline import sync_workspace
from engines.registry import LanguageRegistry
from utils.session import get_project_root


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


def _select_include_dirs(project_root: Path, arch_dir: Path, force: bool = False):
    """
    Reuses existing configured directories from .arch/config.json (never prompts on --force).
    On first-time initialization with no configured directory prefixes, discovers real top-level
    code directories and writes the selection to config.json.
    """
    config_path = arch_dir / "config.json"
    existing_config = {}
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                existing_config = json.load(f)
        except Exception:
            existing_config = {}

    configured_dirs = [
        k.rstrip("/\\")
        for k, v in existing_config.items()
        if isinstance(v, dict) and k not in ("exclude", ".")
    ]

    if configured_dirs:
        print(f"Using configured directories from {config_path.name}: {', '.join(configured_dirs)}")
        return configured_dirs

    if force and config_path.exists():
        print(f"[Force] Preserving existing {config_path.name} (no directory prefixes configured; indexing workspace root).")
        return []

    skip_dirs = {".git", ".arch", ".venv", "__pycache__", "node_modules", ".mypy_cache", ".pytest_cache", "build", "dist"}
    code_exts = LanguageRegistry.list_extensions()

    code_dirs = set()
    for ext in code_exts:
        for f in project_root.rglob(f"*{ext}"):
            try:
                rel = f.relative_to(project_root)
            except ValueError:
                continue
            if len(rel.parts) <= 1:
                continue
            top = rel.parts[0]
            if top not in skip_dirs and not top.startswith(".") and (project_root / top).is_dir():
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


def cmd_init(args):
    """Initialize workspace and index symbols."""
    project_root = get_project_root(args)
    force = getattr(args, "force", False)

    # 1. Workspace init
    if force:
        arch_dir = project_root / ".arch"
        db_path = arch_dir / "arch.db"
        if db_path.exists():
            print(f"[Force] Deleting database at {db_path}...")
            db_path.unlink()
        for f in arch_dir.glob("index_*.scip"):
            f.unlink()
            print(f"[Force] Deleted {f.name}")
        config_path = arch_dir / "config.json"
        if config_path.exists():
            print(
                f"[Force] Preserving existing {config_path}. "
                "Edit .arch/config.json directly to change included or excluded directories."
            )

    arch_dir = initialize_workspace(project_root)
    print(f"\nWorkspace folder initialized at {arch_dir}")

    # 2. Auto-recognition
    languages = detect_languages(project_root)
    print("\n[Auto-Recognition] System Status:")
    if not languages:
        print("  - Languages: No supported languages detected.")
    else:
        print(f"  - Detected languages: {', '.join(languages)}")
        env_status = verify_environment(languages)
        for lang, available in env_status.items():
            status_str = "Available" if available else "NOT found on PATH"
            print(f"    * {lang.capitalize()} Toolchain: {status_str}")

    # 3. User selections
    selected_languages = _select_languages(languages)
    _select_include_dirs(project_root, arch_dir, force=force)

    # 4. Create shared repository for indexing and linking
    db_conn = DbConnection(arch_dir / "arch.db")
    repository = Repository(db_conn)

    # Sync compliance rules from config.json now that it is configured
    try:
        from setup.initializer import sync_rules_to_db
        from utils.helpers import load_config
        sync_rules_to_db(repository, load_config(project_root))
    except Exception as e:
        print(f"Warning: Failed to sync compliance rules: {e}", file=sys.stderr)

    # 5. Run Unified Synchronization Pipeline (Tree-sitter AST, SCIP Semantic, and FFI)
    print("\n--- Running Workspace Synchronization Pipeline ---")
    sync_res = sync_workspace(
        repository,
        project_root,
        languages=selected_languages,
        force=force,
        run_ffi=True,
    )
    indexed_any = bool(sync_res["indexed_languages"] or sync_res["ast_symbol_count"] > 0)
    print(f"  Tree-sitter: Extracted {sync_res['ast_symbol_count']} symbols.")
    if sync_res["indexed_languages"]:
        print(f"  SCIP: Indexed {', '.join(sync_res['indexed_languages'])}.")
    if sync_res["ffi_edges_created"]:
        print(f"  FFI: Created {sync_res['ffi_edges_created']} cross-language edges.")

    db_conn.close()

    # 6. Summary
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
