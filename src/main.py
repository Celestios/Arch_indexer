import sys
import argparse
from pathlib import Path
from contextlib import contextmanager

from setup.initializer import initialize_workspace

from db.connection import DbConnection
from db.repository import Repository
from engines.scip_wrapper import ScipWrapper
from auditor.analyzer import Auditor
from change_tracker.watcher import start_watcher
from auditor.validator import ConfigValidator
from utils.progress import make_progress_callback


def get_project_root(args) -> Path:
    import os
    env_root = os.environ.get("ARCH_PROJECT_ROOT")
    if env_root and (not hasattr(args, "project_root") or args.project_root == "."):
        return Path(env_root).resolve()
    return Path(args.project_root).resolve()


@contextmanager
def workspace_session(args):
    """Context manager that validates workspace, creates Repository, and handles cleanup."""
    project_root = get_project_root(args)
    arch_dir = project_root / ".arch"
    if not arch_dir.exists():
        print("Error: Workspace not initialized. Run 'arch init' first.", file=sys.stderr)
        sys.exit(1)
    db_conn = DbConnection(arch_dir / "arch.db")
    repository = Repository(db_conn)
    try:
        yield project_root, arch_dir, repository
    finally:
        db_conn.close()


def resolve_filepath(repository, raw_path: str) -> str:
    """Resolve a filepath against the database, trying exact match then suffix fallback."""
    file_info = repository.files.get_file(raw_path)
    if file_info:
        return raw_path
    all_files = repository.files.get_all_files_metadata()
    for fp in all_files.keys():
        if fp.replace("\\", "/").endswith(raw_path.replace("\\", "/")):
            return fp
    return None


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
        bin_dir = Path(__file__).resolve().parent.parent / "bin"
    target_models_dir = bin_dir / "models"
    model_path = target_models_dir / "model.onnx"
    tokenizer_path = target_models_dir / "tokenizer.json"
    codeql_dir = bin_dir / "codeql"
    codeql_exe = codeql_dir / "codeql.exe"
    model_installed = model_path.exists() and tokenizer_path.exists()
    codeql_installed = codeql_exe.exists() or (shutil.which("codeql") is not None)
    return bin_dir, target_models_dir, model_path, tokenizer_path, codeql_dir, codeql_exe, model_installed, codeql_installed


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


def _select_codeql(codeql_installed, codeql_dir, shutil_mod):
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
                    if codeql_dir.exists():
                        try:
                            shutil_mod.rmtree(codeql_dir)
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


def _run_sci_indexer(project_root, arch_dir, selected_languages, embedder, force):
    """Run SCIP indexer for selected languages. Returns True if any language was indexed."""
    if not selected_languages:
        return False
    print("\n--- Running Code Graph Indexer ---")
    db_conn = DbConnection(arch_dir / "arch.db")
    repository = Repository(db_conn)
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
    db_conn.close()
    return indexed_any


def _build_codeql_dbs(project_root, arch_dir, bin_dir, selected_languages, cql_ready):
    """Build CodeQL databases and Dart analyzer DB. Returns dart_analyzer instance."""
    if not (cql_ready and selected_languages):
        return None
    codeql_lang_map = {
        "rust": "rust", "go": "go", "java": "java", "python": "python",
        "typescript": "javascript",
    }
    cql_langs = [codeql_lang_map[l] for l in selected_languages if l in codeql_lang_map]
    dart_analyzer = None

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


def _extract_codeql_kinds(arch_dir, bin_dir, selected_languages, cql_ready):
    """Extract symbol kinds from CodeQL databases."""
    if not (cql_ready and selected_languages):
        return
    codeql_lang_map = {
        "rust": "rust", "go": "go", "java": "java", "python": "python",
        "typescript": "javascript",
    }
    print("\n--- Extracting Symbol Kinds from CodeQL ---")
    try:
        from engines.codeql_wrapper import CodeQlWrapper
        codeql = CodeQlWrapper(bin_dir)
        if codeql.is_available():
            db_conn = DbConnection(arch_dir / "arch.db")
            with db_conn.session() as conn:
                for lang in selected_languages:
                    cql_lang = codeql_lang_map.get(lang, lang)
                    db_dir = arch_dir / f"codeql_db_{cql_lang}"
                    if not db_dir.exists():
                        db_dir = arch_dir / "codeql_db"
                    if not db_dir.exists():
                        continue
                    kinds = codeql.extract_kinds(db_dir, cql_lang)
                    if kinds:
                        updated = 0
                        for entry in kinds:
                            sym_name, kind, file_path, line = entry["name"], entry["kind"], entry["file"], entry["line"]
                            file_path = file_path.replace("\\", "/")
                            res = conn.execute(
                                "UPDATE symbols SET kind = ? WHERE kind = 'UnspecifiedKind' AND filepath LIKE ? AND start_line = ?",
                                (kind, f"%{file_path}", line)
                            )
                            if res.rowcount == 0:
                                res = conn.execute(
                                    "UPDATE symbols SET kind = ? WHERE kind = 'UnspecifiedKind' AND (symbol LIKE ? OR symbol = ?)",
                                    (kind, f"%{sym_name}%", sym_name)
                                )
                            updated += res.rowcount
                        print(f"  [{lang}] Updated {updated} symbol kinds from CodeQL.")
                    else:
                        print(f"  [{lang}] No kind data extracted from CodeQL.")
            db_conn.close()
    except Exception as e:
        print(f"  Warning: Kind extraction failed: {e}")


def _link_ffi(project_root, arch_dir, bin_dir, selected_languages, cql_ready, dart_analyzer):
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
                db_conn = DbConnection(arch_dir / "arch.db")
                repository = Repository(db_conn)
                linker = FfiLinker(repository)
                edges_created = linker.link(all_matches)
                db_conn.close()
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

    bin_dir, target_models_dir, model_path, tokenizer_path, codeql_dir, codeql_exe, model_installed, codeql_installed = _resolve_init_paths(project_root)

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
    setup_cql, cql_ready = _select_codeql(codeql_installed, codeql_dir, shutil)

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

    # 6. Run SCIP indexer
    indexed_any = _run_sci_indexer(project_root, arch_dir, selected_languages, embedder, getattr(args, 'force', False))

    # 7. Build CodeQL + Dart databases
    dart_analyzer = _build_codeql_dbs(project_root, arch_dir, bin_dir, selected_languages, cql_ready)

    # 8. Extract symbol kinds
    _extract_codeql_kinds(arch_dir, bin_dir, selected_languages, cql_ready)

    # 9. FFI cross-language linking
    _link_ffi(project_root, arch_dir, bin_dir, selected_languages, cql_ready, dart_analyzer)

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


def cmd_audit(args):
    """Run architectural compliance audit."""
    with workspace_session(args) as (project_root, arch_dir, repository):
        auditor = Auditor(repository, project_root)
        violations = auditor.run_audit()

        if violations:
            print(f"\nFound {len(violations)} violations:")
            for v in violations:
                print(f"  [{v['rule_id']}] {v['filepath']}:{v['line']} — {v['message']}")
        else:
            print("No violations found.")


def cmd_report(args):
    """Generates a codebase report."""
    with workspace_session(args) as (project_root, arch_dir, repository):
        from reporter.generator import Reporter
        reporter = Reporter(repository)
        try:
            report_text = reporter.generate_report(args.name, args.format)
            print(report_text)
        except KeyError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)


def cmd_set_status(args):
    """Sets manual AI compliance status flag for a file."""
    with workspace_session(args) as (project_root, arch_dir, repository):
        status = args.status.upper()
        if status not in ("COMPLIANT", "VIOLATION_DETECTED"):
            print(f"Error: Invalid manual compliance status choice: {args.status}. Allowed: COMPLIANT, VIOLATION_DETECTED.", file=sys.stderr)
            sys.exit(1)

        if status == "VIOLATION_DETECTED" and not args.justification:
            print("Error: Justification must be provided when flagging a file as VIOLATION_DETECTED.", file=sys.stderr)
            sys.exit(1)

        filepath = resolve_filepath(repository, args.filepath)
        if not filepath:
            print(f"Error: File '{args.filepath}' is not registered in the database.", file=sys.stderr)
            sys.exit(1)

        repository.files.update_file_manual_status(filepath, status, args.justification)

        repository.compliance.delete_manual_violations(filepath)
        if status == "VIOLATION_DETECTED":
            import hashlib
            violation_text = f"manual_logical_audit_{filepath}_{args.justification}"
            violation_id = hashlib.sha256(violation_text.encode("utf-8")).hexdigest()[:16]

            repository.compliance.add_violation(
                violation_id=violation_id,
                rule_id="logical_audit",
                symbol=None,
                filepath=filepath,
                line=1,
                message=args.justification,
                origin="manual"
            )

        print(f"Successfully updated manual status for '{filepath}' to '{status}'.")


def cmd_set_fields(args):
    """Sets manual fields for a file."""
    with workspace_session(args) as (project_root, arch_dir, repository):
        import json
        try:
            fields = json.loads(args.fields_json)
        except Exception as e:
            print(f"Error: Invalid JSON fields payload: {e}", file=sys.stderr)
            sys.exit(1)

        filepath = resolve_filepath(repository, args.filepath)
        if not filepath:
            print(f"Error: File '{args.filepath}' is not registered in the database.", file=sys.stderr)
            sys.exit(1)

        file_info = repository.files.get_file(filepath)
        current_fields = {}
        if file_info.get("manual_fields"):
            try:
                current_fields = json.loads(file_info["manual_fields"])
            except Exception:
                pass

        for k, v in fields.items():
            if v is None:
                current_fields.pop(k, None)
            else:
                current_fields[k] = v

        repository.files.update_file_manual_fields(filepath, current_fields, args.justification)

        auditor = Auditor(repository, project_root)
        auditor.run_audit()

        print(f"Successfully updated manual fields for '{filepath}' to: {current_fields}.")


def cmd_clear_pending(args):
    """Clears all pending audit flags in the database."""
    with workspace_session(args) as (project_root, arch_dir, repository):
        repository.files.clear_all_pending_audits(args.justification)
        auditor = Auditor(repository, project_root)
        auditor.run_audit()
        print("Successfully cleared pending audit status for all files.")


def cmd_watch(args):
    """Watches the project root for file changes and auto-indexes/audits."""
    project_root = get_project_root(args)
    debounce = args.debounce
    try:
        start_watcher(project_root, debounce)
    except Exception as e:
        print(f"Watcher error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_analyze(args):
    """Validates the architectural configuration ontology (config.json) completeness and sanity."""
    project_root = get_project_root(args)
    validator = ConfigValidator(project_root)
    res = validator.validate()

    print("=== Configuration Sanity & Completeness Analysis ===")
    
    if res["warnings"]:
        print(f"\n[WARNING] Reachability warnings ({len(res['warnings'])}):")
        for warning in res["warnings"]:
            print(f"  - {warning}")
    else:
        print("\n[OK] Value reachability check passed (no unreachable values).")

    if res["errors"]:
        print(f"\n[ERROR] Referential integrity failures ({len(res['errors'])}):")
        for error in res["errors"]:
            print(f"  - {error}")
        print("\nValidation failed.", file=sys.stderr)
        sys.exit(1)
    else:
        print("[OK] Referential integrity validation passed.")
        print("\nValidation succeeded.")
        sys.exit(0)


def cmd_impact(args):
    """Performs blast radius analysis for a symbol by computing its transitive callers and callees."""
    project_root = get_project_root(args)
    arch_dir = project_root / ".arch"
    db_path = arch_dir / "arch.db"

    if not db_path.exists():
        print(f"Error: Arch database not found at {db_path}. Please run 'arch init' first.", file=sys.stderr)
        sys.exit(1)

    db_conn = DbConnection(db_path)
    repository = Repository(db_conn)

    try:
        closure = repository.edges.get_transitive_closure(args.symbol, max_depth=args.max_depth)
    except Exception as e:
        print(f"Error computing blast radius: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db_conn.close()

    upstream = closure.get("upstream", [])
    downstream = closure.get("downstream", [])

    print(f"=== Blast Radius for: {args.symbol} ===")
    
    print("\n--- Upstream Callers (Who calls this?) ---")
    if not upstream:
        print("*No transitive upstream callers found.*")
    else:
        upstream_sorted = sorted(upstream, key=lambda x: x["depth"])
        for item in upstream_sorted:
            path_str = " ──> ".join(f"{s.split('.')[-1]}" for s in item["path"])
            print(f"- {item['symbol']} [Depth: {item['depth']}]")
            print(f"  Path: {path_str}")

    print("\n--- Downstream Callees (What does this call?) ---")
    if not downstream:
        print("*No transitive downstream callees found.*")
    else:
        downstream_sorted = sorted(downstream, key=lambda x: x["depth"])
        for item in downstream_sorted:
            path_str = " ──> ".join(f"{s.split('.')[-1]}" for s in item["path"])
            print(f"- {item['symbol']} [Depth: {item['depth']}]")
            print(f"  Path: {path_str}")


def cmd_mcp(args):
    """Starts the FastMCP server."""
    import os
    project_root = get_project_root(args)
    os.environ["ARCH_PROJECT_ROOT"] = str(project_root)


    # We must ensure that the path to src is in sys.path
    src_dir = Path(__file__).resolve().parent
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

    from interface.server import run_server
    run_server()


def main():

    parser = argparse.ArgumentParser(
        prog="arch",
        description="Arch-mcp: Agent-Native Code Intelligence & Compliance Engine"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # mcp
    mcp_parser = subparsers.add_parser("mcp", help="Start the MCP server")
    mcp_parser.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    mcp_parser.set_defaults(func=cmd_mcp)

    # init (unified setup + indexer)
    init_parser = subparsers.add_parser("init", help="Initialize workspace, download models, and index symbols")
    init_parser.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    init_parser.add_argument("--force", action="store_true", help="Force clean rebuild: delete DB and re-index from scratch")
    init_parser.set_defaults(func=cmd_init)

    # audit
    audit_parser = subparsers.add_parser("audit", help="Run compliance audit")
    audit_parser.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    audit_parser.set_defaults(func=cmd_audit)

    # report
    report_parser = subparsers.add_parser("report", help="Generate workspace data reports")
    report_parser.add_argument("name", choices=["overview", "compliance"], help="Report name")
    report_parser.add_argument("--format", choices=["markdown", "json"], default="markdown", help="Output format")
    report_parser.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    report_parser.set_defaults(func=cmd_report)

    # set-status
    set_status_parser = subparsers.add_parser("set-status", help="Set manual AI logical compliance status for a file")
    set_status_parser.add_argument("filepath", help="Filepath to the target file")
    set_status_parser.add_argument("status", choices=["COMPLIANT", "VIOLATION_DETECTED"], help="Manual logical compliance status")
    set_status_parser.add_argument("justification", nargs="?", default=None, help="Justification comment (required for VIOLATION_DETECTED)")
    set_status_parser.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    set_status_parser.set_defaults(func=cmd_set_status)

    # set-fields
    set_fields_parser = subparsers.add_parser("set-fields", help="Set manual metadata fields for a file")
    set_fields_parser.add_argument("filepath", help="Filepath to the target file")
    set_fields_parser.add_argument("fields_json", help="JSON string of fields to update")
    set_fields_parser.add_argument("justification", nargs="?", default=None, help="Optional update justification")
    set_fields_parser.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    set_fields_parser.set_defaults(func=cmd_set_fields)

    # clear-pending
    clear_pending_parser = subparsers.add_parser("clear-pending", help="Clear all pending audit flags")
    clear_pending_parser.add_argument("justification", help="Justification comment for clearing all pending audits")
    clear_pending_parser.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    clear_pending_parser.set_defaults(func=cmd_clear_pending)

    # watch
    watch_parser = subparsers.add_parser("watch", help="Watch workspace and auto-index and audit on changes")
    watch_parser.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    watch_parser.add_argument("--debounce", type=float, default=3.0, help="Debounce delay in seconds")
    watch_parser.set_defaults(func=cmd_watch)

    # analyze
    analyze_parser = subparsers.add_parser("analyze", help="Validate configuration completeness and sanity")
    analyze_parser.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    analyze_parser.set_defaults(func=cmd_analyze)

    # impact
    impact_parser = subparsers.add_parser("impact", help="Perform blast radius / transitive dependency analysis for a symbol")
    impact_parser.add_argument("symbol", help="Target symbol name")
    impact_parser.add_argument("--max-depth", type=int, default=3, help="Maximum traversal depth (default: 3)")
    impact_parser.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    impact_parser.set_defaults(func=cmd_impact)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
