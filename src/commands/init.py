import sys
from pathlib import Path

from setup.initializer import initialize_workspace
from db.connection import DbConnection
from db.repository import Repository
from engines.scip_wrapper import ScipWrapper
from utils.progress import make_progress_callback
from utils.helpers import CODEQL_LANG_MAP
from utils.session import get_project_root


def _resolve_init_paths(project_root: Path):
    """Resolve bin_dir and component paths for the init command."""
    import shutil
    if getattr(sys, 'frozen', False):
        exe_dir = Path(sys.executable).resolve().parent
        if (exe_dir / "bin").exists():
            bin_dir = exe_dir / "bin"
        else:
            bin_dir = exe_dir.parent / "bin"
    else:
        bin_dir = Path(__file__).resolve().parent.parent.parent / "bin"
    target_models_dir = bin_dir / "models"
    model_path = target_models_dir / "model.onnx"
    tokenizer_path = target_models_dir / "tokenizer.json"
    codeql_cli_dir = bin_dir / "codeql"
    codeql_exe = codeql_cli_dir / "codeql.exe"
    model_installed = model_path.exists() and tokenizer_path.exists()
    codeql_installed = codeql_exe.exists() or (shutil.which("codeql") is not None)
    return bin_dir, target_models_dir, model_path, tokenizer_path, codeql_cli_dir, codeql_exe, model_installed, codeql_installed


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


def _select_model(model_installed):
    """Interactively prompt user for ONNX model setup."""
    setup_model = False
    choice = "1"
    if model_installed:
        if sys.stdin.isatty():
            try:
                print("\n--- ONNX Embedding Model Options ---")
                change_ans = input("ONNX Embedding Model assets are already present. Do you want to change/re-download? [y/N]: ").strip().lower()
                if change_ans in ("y", "yes"):
                    setup_model = True
            except (KeyboardInterrupt, EOFError):
                pass
    else:
        setup_model = True

    if setup_model:
        print("\n--- ONNX Embedding Model Options ---")
        print("Arch uses a local ONNX model to generate vector embeddings for semantic search.")
        print("  [1] all-MiniLM-L6-v2 (Lightweight & Fast, ~90MB download, 384 dimensions)")
        print("  [2] bge-small-en-v1.5 (High Performance, ~130MB download, 384 dimensions)")
        print("  [3] all-mpnet-base-v2 (Maximum Accuracy, ~430MB download, 768 dimensions)")
        print("  [4] Skip model download (semantic search will be disabled)")
        if sys.stdin.isatty():
            try:
                choice = input("\nChoose an option [1-4] (default: 1): ").strip()
                if not choice:
                    choice = "1"
            except (KeyboardInterrupt, EOFError):
                print("\nDefaulting to option [1] due to user interruption.")
                choice = "1"
        else:
            print("\nNon-interactive session. Defaulting to option [1].")
            choice = "1"
    return setup_model, choice


def _select_codeql(codeql_installed, codeql_cli_dir, shutil_mod):
    """Interactively prompt user for CodeQL setup."""
    import shutil as shutil_local
    shutil_mod = shutil_mod or shutil_local
    setup_cql = False
    cql_ready = codeql_installed

    if codeql_installed:
        if sys.stdin.isatty():
            try:
                print("\n--- CodeQL CLI Options ---")
                change_cql = input("CodeQL CLI is already installed. Do you want to re-download/update? [y/N]: ").strip().lower()
                if change_cql in ("y", "yes"):
                    setup_cql = True
                    if codeql_cli_dir.exists():
                        try:
                            shutil_mod.rmtree(codeql_cli_dir)
                        except Exception as e:
                            print(f"Warning: Could not clear existing codeql folder: {e}")
            except (KeyboardInterrupt, EOFError):
                pass
    else:
        if sys.stdin.isatty():
            print("\n--- CodeQL CLI Options ---")
            print("Arch can use CodeQL to trace data flow paths (e.g. from source endpoint to database sink).")
            print("This requires downloading the CodeQL CLI binary (~200MB download, extracting to ~500MB).")
            try:
                cql_ans = input("\nSetup CodeQL CLI? [Y/n]: ").strip().lower()
                setup_cql = cql_ans not in ("n", "no")
            except (KeyboardInterrupt, EOFError):
                print("\nDefaulting to option [Y] due to user interruption.")
                setup_cql = True
        else:
            print("\nNon-interactive session. Skipping CodeQL CLI setup.")
            setup_cql = False
    return setup_cql, cql_ready


def _select_include_dirs(project_root, arch_dir):
    """Interactively prompt user to select directories to index. Writes selection to config.json."""
    import json
    skip_dirs = {".git", ".arch", ".venv", "__pycache__", "node_modules", ".mypy_cache", ".pytest_cache", "build", "dist"}
    code_exts = {ext for ext, lang in {".rs": "rust", ".dart": "dart", ".py": "python", ".go": "go", ".js": "javascript", ".ts": "typescript", ".java": "java"}.items()}

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
        return

    print("\n--- Directory Indexing Options ---")
    print("Directories containing code files:")
    for idx, d in enumerate(code_dirs, 1):
        print(f"  [{idx}] {d}")
    try:
        choice = input(f"Choose directories [1-{len(code_dirs)}] (comma-separated, e.g., 1,2, default: all): ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nDefaulting to all directories.")
        choice = ""

    selected = code_dirs
    if choice:
        try:
            indices = [int(i.strip()) for i in choice.split(",") if i.strip().isdigit()]
            valid = [code_dirs[i - 1] for i in indices if 1 <= i <= len(code_dirs)]
            if valid:
                selected = valid
            else:
                print("Invalid selection. Defaulting to all directories.")
        except ValueError:
            print("Invalid input. Defaulting to all directories.")

    config = {d: {} for d in selected}
    config_path = arch_dir / "config.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    print(f"  Indexed directories: {', '.join(selected)}")


def _setup_model(setup_model, choice, target_models_dir, model_path, tokenizer_path, bin_dir):
    """Download or load ONNX embedding model. Returns LocalEmbedder or None."""
    embedder = None
    if choice == "4":
        return embedder
    if setup_model:
        print("\n--- Downloading ONNX Model Assets ---")
        try:
            from setup.embedder_bootstrap import EMBEDDING_MODELS
            model_info = EMBEDDING_MODELS.get(choice, EMBEDDING_MODELS["1"])
            target_models_dir.mkdir(parents=True, exist_ok=True)
            print(f"Downloading: {model_info['name']}")
            if not model_path.exists():
                from setup.downloader import download_file
                download_file(model_info["model_url"], model_path, progress_callback=make_progress_callback("model.onnx"))
            if not tokenizer_path.exists():
                from setup.downloader import download_file
                download_file(model_info["tokenizer_url"], tokenizer_path, progress_callback=make_progress_callback("tokenizer.json"))
            from engines.embedder import LocalEmbedder
            embedder = LocalEmbedder(bin_dir)
            print("\nONNX model downloaded and initialized successfully.")
        except Exception as e:
            print(f"\nWarning: Could not set up embedder ({e}).")
            print("Troubleshooting: Ensure you have active internet connection. You can re-run 'arch init' to retry.")
    else:
        try:
            from engines.embedder import LocalEmbedder
            embedder = LocalEmbedder(bin_dir)
            print("\nONNX model verified and loaded successfully.")
        except Exception as e:
            print(f"\nWarning: Could not load existing embedding model ({e}). Re-run 'arch init' and choose to re-download.")
    return embedder


def _run_sci_indexer(project_root, repository, selected_languages, embedder, force):
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
            ScipWrapper.ingest_index(repository, parsed, embedder, project_root, force=force)
            print(f"  [{lang}] {len(parsed['symbols'])} symbols ingested.")
            indexed_any = True
        else:
            print(f"  [{lang}] Indexing failed. Verify environment settings.", file=sys.stderr)
    return indexed_any


def _build_codeql_dbs(project_root, arch_dir, bin_dir, selected_languages, cql_ready):
    """Build CodeQL databases and Dart analyzer DB. Returns dart_analyzer instance."""
    dart_analyzer = None

    if "dart" in selected_languages:
        try:
            from engines.dart_analyzer import DartAnalyzerWrapper
            dart_analyzer = DartAnalyzerWrapper(arch_dir)
            if dart_analyzer.is_available():
                print("\n--- Running Dart Analyzer Database Generator ---")
                dart_analyzer.create_database(
                    source_root=project_root,
                    db_output_dir=arch_dir / "dart_analyzer_db",
                    language="dart"
                )
            else:
                print("\n[DartAnalyzer] analyzer package not available, skipping.")
                dart_analyzer = None
        except ImportError:
            print("\n[DartAnalyzer] Failed to import, skipping.")
            dart_analyzer = None

    if cql_ready and selected_languages:
        cql_langs = [CODEQL_LANG_MAP[l] for l in selected_languages if l in CODEQL_LANG_MAP]
    else:
        cql_langs = []

    if cql_langs:
        try:
            from setup.indexers import download_codeql_packs
            download_codeql_packs(bin_dir, cql_langs)
        except Exception as e:
            print(f"  Warning: CodeQL pack download failed: {e}")

        build_cql = True
        if sys.stdin.isatty():
            try:
                lang_str = ", ".join(cql_langs)
                cql_db_ans = input(f"\nBuild CodeQL database for {lang_str}? [Y/n]: ").strip().lower()
                build_cql = cql_db_ans not in ("n", "no")
            except (KeyboardInterrupt, EOFError):
                build_cql = True
        else:
            build_cql = False

        if build_cql:
            print("\n--- Running CodeQL Database Generator ---")
            try:
                from engines.codeql_wrapper import CodeQlWrapper
                codeql = CodeQlWrapper(bin_dir)
                cql_langs_filtered = [l for l in cql_langs if l != "dart"]
                for lang in cql_langs_filtered:
                    db_output_dir = arch_dir / f"codeql_db_{lang}"
                    print(f"\n[CodeQL] Building database for {lang}...")
                    success = codeql.create_database(
                        source_root=project_root,
                        db_output_dir=db_output_dir,
                        language=lang
                    )
                    if success:
                        print(f"  [{lang}] CodeQL database built successfully.")
                    else:
                        print(f"  [{lang}] Warning: CodeQL database build failed.")
            except Exception as e:
                print(f"Error creating CodeQL database: {e}")

    return dart_analyzer


def _extract_codeql_kinds(db_conn, arch_dir, bin_dir, selected_languages, cql_ready, project_root=None):
    """Extract symbol kinds from CodeQL databases."""
    if not (cql_ready and selected_languages):
        return
    print("\n--- Extracting Symbol Kinds from CodeQL ---")
    try:
        from engines.codeql_wrapper import CodeQlWrapper
        from utils.exclusions import load_include_dirs, is_included
        codeql = CodeQlWrapper(bin_dir)
        include_dirs = load_include_dirs(project_root) if project_root else None
        if codeql.is_available():
            with db_conn.session() as conn:
                for lang in selected_languages:
                    if lang not in CODEQL_LANG_MAP:
                        continue
                    cql_lang = CODEQL_LANG_MAP[lang]
                    db_dir = arch_dir / f"codeql_db_{cql_lang}"
                    if not db_dir.exists():
                        db_dir = arch_dir / "codeql_db"
                    if not db_dir.exists():
                        continue
                    kinds = codeql.extract_kinds(db_dir, cql_lang)
                    if kinds:
                        updated = 0
                        already_typed = 0
                        no_file = 0
                        no_sym = 0
                        scope_skipped = 0
                        for entry in kinds:
                            sym_name, kind, file_path, line = entry["name"], entry["kind"], entry["file"], entry["line"]
                            file_path_norm = file_path.replace("/", "\\")
                            if include_dirs and not is_included(file_path_norm, include_dirs):
                                scope_skipped += 1
                                continue
                            short_name = sym_name.rsplit(".", 1)[-1] if "." in sym_name else sym_name
                            res = conn.execute(
                                "UPDATE symbols SET kind = ? WHERE kind = 'UnspecifiedKind' AND filepath LIKE ? AND symbol LIKE ?",
                                (kind, f"%{file_path_norm}%", f"%{short_name}%")
                            )
                            if res.rowcount > 0:
                                updated += res.rowcount
                            else:
                                fp_hit = conn.execute(
                                    "SELECT COUNT(*) FROM symbols WHERE filepath LIKE ? AND symbol LIKE ?",
                                    (f"%{file_path_norm}%", f"%{short_name}%")
                                ).fetchone()[0]
                                if fp_hit > 0:
                                    already_typed += 1
                                else:
                                    file_hit = conn.execute(
                                        "SELECT COUNT(*) FROM symbols WHERE filepath LIKE ?",
                                        (f"%{file_path_norm}%",)
                                    ).fetchone()[0]
                                    if file_hit == 0:
                                        no_file += 1
                                    else:
                                        no_sym += 1
                        print(f"  [{lang}] CodeQL results: {len(kinds)} | scope-skipped: {scope_skipped} | updated: {updated} | already-typed: {already_typed} | no-file: {no_file} | no-sym: {no_sym}")
                    else:
                        print(f"  [{lang}] No kind data extracted from CodeQL.")
    except Exception as e:
        print(f"  Warning: Kind extraction failed: {e}")


def _link_ffi(project_root, repository, arch_dir, bin_dir, selected_languages, cql_ready, dart_analyzer):
    """Run FFI cross-language linking."""
    if len(selected_languages) <= 1:
        return
    print("\n--- Running FFI Cross-Language Linker ---")
    try:
        from engines.ffi_extractor import FfiExtractor
        from engines.ffi_matcher import FfiMatcher
        from engines.ffi_linker import FfiLinker

        codeql_wrappers = {}
        if cql_ready:
            from engines.codeql_wrapper import CodeQlWrapper
            try:
                codeql = CodeQlWrapper(bin_dir)
                if codeql.is_available():
                    for lang in selected_languages:
                        if lang == "dart":
                            continue
                        db_dir = arch_dir / f"codeql_db_{lang}"
                        if db_dir.exists():
                            codeql_wrappers[lang] = codeql
            except Exception:
                pass

        extractor = FfiExtractor(codeql_wrappers=codeql_wrappers, dart_analyzer=dart_analyzer)
        surfaces = extractor.extract_all(project_root, languages=selected_languages)

        if surfaces:
            matcher = FfiMatcher()
            by_lang = {}
            for s in surfaces:
                by_lang.setdefault(s.language, []).append(s)

            all_matches = []
            lang_keys = list(by_lang.keys())
            for i in range(len(lang_keys)):
                for j in range(i + 1, len(lang_keys)):
                    matches = matcher.match(by_lang[lang_keys[i]], by_lang[lang_keys[j]])
                    all_matches.extend(matches)

            if all_matches:
                linker = FfiLinker(repository)
                edges_created = linker.link(all_matches)
                print(f"  FFI linking complete: {edges_created} cross-language edges created.")
            else:
                print("  No FFI matches found across languages.")
        else:
            print("  No FFI surfaces detected.")
    except Exception as e:
        print(f"  Warning: FFI linking failed: {e}")


def cmd_init(args):
    """Unified setup command: initialize workspace, download models, set up CodeQL, and index symbols."""
    import shutil
    project_root = get_project_root(args)

    bin_dir, target_models_dir, model_path, tokenizer_path, codeql_cli_dir, codeql_exe, model_installed, codeql_installed = _resolve_init_paths(project_root)

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
        print("  - Languages: No supported languages (Rust, Dart) detected.")
        print("    (Note: Arch works best on Dart/Flutter or Rust codebases.)")
    else:
        print(f"  - Detected languages: {', '.join(languages)}")
        env_status = ScipWrapper.verify_environment(languages)
        for lang, available in env_status.items():
            status_str = "Available" if available else "NOT found on PATH"
            print(f"    * {lang.capitalize()} Toolchain: {status_str}")
            if not available:
                if lang == "dart":
                    print("      -> Recommendation: Please install Dart/Flutter SDK.")
                elif lang == "rust":
                    print("      -> Recommendation: Please install Rust (rustup/rust-analyzer).")
    print("\n[Local Components] Dependency Status:")
    print(f"  - ONNX Embedding Model: {'Installed' if model_installed else 'Not downloaded'}")
    print(f"  - CodeQL CLI:           {'Installed' if codeql_installed else 'Not downloaded'}")

    # 3. User selections
    selected_languages = _select_languages(languages)
    setup_model, model_choice = _select_model(model_installed)
    setup_cql, cql_ready = _select_codeql(codeql_installed, codeql_cli_dir, shutil)
    _select_include_dirs(project_root, arch_dir)

    # 4. Setup CodeQL
    if setup_cql:
        print("\n--- Bootstrapping CodeQL CLI ---")
        try:
            from setup.indexers import bootstrap_codeql
            bootstrap_codeql(bin_dir, progress_callback=make_progress_callback("codeql.zip"))
            cql_ready = True
        except Exception as e:
            print(f"\nWarning: CodeQL setup failed ({e}). Tracer tool will not be available.")
    elif cql_ready:
        print("\nCodeQL CLI is ready (using existing installation).")

    # 5. Setup model
    embedder = _setup_model(setup_model, model_choice, target_models_dir, model_path, tokenizer_path, bin_dir)

    # 6. Create shared repository for indexing and linking
    db_conn = DbConnection(arch_dir / "arch.db")
    repository = Repository(db_conn)

    # 7. Run SCIP indexer
    indexed_any = _run_sci_indexer(project_root, repository, selected_languages, embedder, getattr(args, 'force', False))

    # 8. Build CodeQL + Dart databases
    dart_analyzer = _build_codeql_dbs(project_root, arch_dir, bin_dir, selected_languages, cql_ready)

    # 9. Extract symbol kinds
    _extract_codeql_kinds(db_conn, arch_dir, bin_dir, selected_languages, cql_ready, project_root)

    # 10. FFI cross-language linking
    _link_ffi(project_root, repository, arch_dir, bin_dir, selected_languages, cql_ready, dart_analyzer)

    db_conn.close()

    # 10. Summary
    if selected_languages:
        if indexed_any:
            print("\nIndexing completed successfully!")
        else:
            print("\nIndexing failed. Setup complete, but no symbols were ingested.")
    else:
        if not languages:
            print("\nNo supported toolchains detected. Setup complete, but index could not be built.")
        else:
            print("\nNo languages selected for indexing. Setup complete, but index could not be built.")

    print("\n====================================================")
    print(" Arch setup is complete! Ready to start MCP Server. ")
    print("====================================================")
