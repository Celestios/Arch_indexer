import os
import sys
import argparse
from pathlib import Path

from setup.initializer import initialize_workspace
from setup.mcp_config import register_claude_desktop_mcp
from db.connection import DbConnection
from db.repository import Repository
from engines.scip_wrapper import ScipWrapper
from auditor.analyzer import Auditor


def make_progress_callback(filename: str):
    def callback(downloaded: int, total_size: int):
        percent = (downloaded / total_size) * 100 if total_size else 0
        bar_len = 30
        filled_len = int(round(bar_len * downloaded / float(total_size))) if total_size else 0
        bar = '=' * filled_len + '-' * (bar_len - filled_len)
        sys.stdout.write(f"\r[{filename}] [{bar}] {downloaded / (1024*1024):.1f}/{total_size / (1024*1024):.1f} MB ({percent:.1f}%)")
        sys.stdout.flush()
        if downloaded == total_size:
            sys.stdout.write("\n")
    return callback



def cmd_init(args):
    """Unified setup command: initialize workspace, download models, set up CodeQL, and index symbols."""
    project_root = Path(args.project_root).resolve()
    print("====================================================")
    print("      Arch: Code Intelligence & Compliance Setup     ")
    print("====================================================")

    # 1. Scanner/Auto-recognition
    languages = ScipWrapper.detect_languages(project_root)
    if not languages:
        print("\n[Auto-Recognition] No supported language toolchains (Rust, Dart) detected.")
        print("Arch works best on Dart/Flutter or Rust codebases.")
        print("Please ensure your project contains Cargo.toml or pubspec.yaml.")
    else:
        print(f"\n[Auto-Recognition] Detected languages: {', '.join(languages)}")
        env_status = ScipWrapper.verify_environment(languages)
        for lang, available in env_status.items():
            status_str = "Available" if available else "NOT found on PATH"
            print(f"  - {lang.capitalize()} Toolchain: {status_str}")
            if not available:
                if lang == "dart":
                    print("    -> Recommendation: Please install Dart/Flutter SDK.")
                elif lang == "rust":
                    print("    -> Recommendation: Please install Rust (rustup/rust-analyzer).")

    # 2. Embedding Model choice
    print("\n--- ONNX Embedding Model Options ---")
    print("Arch uses a local ONNX model to generate vector embeddings for semantic search.")
    print("  [1] all-MiniLM-L6-v2 (Lightweight & Fast, ~90MB download, 384 dimensions)")
    print("  [2] bge-small-en-v1.5 (High Performance, ~130MB download, 384 dimensions)")
    print("  [3] all-mpnet-base-v2 (Maximum Accuracy, ~430MB download, 768 dimensions)")
    print("  [4] Skip model download (semantic search will be disabled)")
    
    choice = "1"
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

    # 2b. CodeQL setup choice
    print("\n--- CodeQL CLI Options ---")
    print("Arch can use CodeQL to trace data flow paths (e.g. from source endpoint to database sink).")
    print("This requires downloading the CodeQL CLI binary (~200MB download, extracting to ~500MB).")
    
    setup_cql = True
    if sys.stdin.isatty():
        try:
            cql_ans = input("\nSetup CodeQL CLI? [Y/n]: ").strip().lower()
            setup_cql = cql_ans not in ("n", "no")
        except (KeyboardInterrupt, EOFError):
            print("\nDefaulting to option [Y] due to user interruption.")
            setup_cql = True
    else:
        print("\nNon-interactive session. Skipping CodeQL CLI setup.")
        setup_cql = False

    # 3. Initialize workspace structure & DB
    arch_dir = initialize_workspace(project_root)
    print(f"\nWorkspace folder initialized at {arch_dir}")
    
    bin_dir = Path(__file__).resolve().parent.parent / "bin"
    target_models_dir = bin_dir / "models"

    # 3b. Setup CodeQL if requested
    cql_ready = False
    if setup_cql:
        print("\n--- Bootstrapping CodeQL CLI ---")
        try:
            from setup.indexers import bootstrap_codeql
            bootstrap_codeql(bin_dir, progress_callback=make_progress_callback("codeql.zip"))
            cql_ready = True
        except Exception as e:
            print(f"\nWarning: CodeQL setup failed ({e}). Tracer tool will not be available.")

    # 4. Bootstrap ONNX model if requested
    embedder = None
    if choice != "4":
        print("\n--- Downloading ONNX Model Assets ---")
        try:
            from setup.embedder_bootstrap import bootstrap_onnx_model, EMBEDDING_MODELS
            
            model_info = EMBEDDING_MODELS.get(choice, EMBEDDING_MODELS["1"])
            model_path = target_models_dir / "model.onnx"
            tokenizer_path = target_models_dir / "tokenizer.json"

            if not (model_path.exists() and tokenizer_path.exists()):
                from setup.downloader import download_file
                target_models_dir.mkdir(parents=True, exist_ok=True)
                print(f"Downloading: {model_info['name']}")
                if not model_path.exists():
                    download_file(model_info["model_url"], model_path, progress_callback=make_progress_callback("model.onnx"))
                if not tokenizer_path.exists():
                    download_file(model_info["tokenizer_url"], tokenizer_path, progress_callback=make_progress_callback("tokenizer.json"))
            else:
                print(f"ONNX Model assets are already present at {target_models_dir}.")

            # Load the local embedder to verify
            from engines.embedder import LocalEmbedder
            embedder = LocalEmbedder(bin_dir)
            print("\nONNX model downloaded and initialized successfully.")
        except Exception as e:
            print(f"\nWarning: Could not set up embedder ({e}).")
            print("Troubleshooting: Ensure you have active internet connection. You can re-run 'arch init' to retry.")

    # 5. Run indexer automatically
    if languages:
        print("\n--- Running Code Graph Indexer ---")
        db_conn = DbConnection(arch_dir / "arch.db")
        repository = Repository(db_conn)
        
        indexed_any = False
        for lang in languages:
            index_path = ScipWrapper.run_indexer(project_root, lang)
            if index_path:
                print(f"  [{lang}] Index generated at {index_path}")
                parsed = ScipWrapper.parse_index(index_path)
                ScipWrapper.ingest_index(repository, parsed, embedder, project_root)
                print(f"  [{lang}] {len(parsed['symbols'])} symbols ingested.")
                indexed_any = True
            else:
                print(f"  [{lang}] Indexing failed. Verify environment settings.", file=sys.stderr)
        
        db_conn.close()
        if indexed_any:
            print("\nIndexing completed successfully!")
        else:
            print("\nIndexing failed. Setup complete, but no symbols were ingested.")
    else:
        print("\nNo supported toolchains detected. Setup complete, but index could not be built.")

    # 5b. CodeQL Database Creation
    if cql_ready and "rust" in languages:
        build_cql = True
        if sys.stdin.isatty():
            try:
                cql_db_ans = input("\nBuild CodeQL database for Rust? (Requires cargo compiler setup) [Y/n]: ").strip().lower()
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
                db_output_dir = arch_dir / "codeql_db"
                success = codeql.create_database(
                    source_root=project_root,
                    db_output_dir=db_output_dir,
                    language="rust"
                )
                if success:
                    print("CodeQL database built successfully.")
                else:
                    print("Warning: CodeQL database build failed. Verify build environments.")
            except Exception as e:
                print(f"Error creating CodeQL database: {e}")

    # 6. Automate MCP configuration in Claude Desktop
    print("\n--- Claude Desktop MCP Configuration ---")
    print("Arch can automatically register itself in your Claude Desktop configuration.")
    register_mcp = True
    if sys.stdin.isatty():
        try:
            mcp_ans = input("Automatically register in Claude Desktop? [Y/n]: ").strip().lower()
            register_mcp = mcp_ans not in ("n", "no")
        except (KeyboardInterrupt, EOFError):
            register_mcp = True
    else:
        register_mcp = False

    if register_mcp:
        register_claude_desktop_mcp(project_root)

    print("\n====================================================")
    print(" Arch setup is complete! Ready to start MCP Server. ")
    print("====================================================")


def cmd_audit(args):
    """Run architectural compliance audit."""
    project_root = Path(args.project_root).resolve()
    arch_dir = project_root / ".arch"

    if not arch_dir.exists():
        print("Error: Workspace not initialized. Run 'arch init' first.", file=sys.stderr)
        sys.exit(1)

    db_conn = DbConnection(arch_dir / "arch.db")
    repository = Repository(db_conn)

    auditor = Auditor(repository, project_root)
    violations = auditor.run_audit()

    if violations:
        print(f"\nFound {len(violations)} violations:")
        for v in violations:
            print(f"  [{v['rule_id']}] {v['filepath']}:{v['line']} — {v['message']}")
    else:
        print("No violations found.")

    db_conn.close()


def cmd_report(args):
    """Generates a codebase report."""
    project_root = Path(args.project_root).resolve()
    arch_dir = project_root / ".arch"

    if not arch_dir.exists():
        print("Error: Workspace not initialized. Run 'arch init' first.", file=sys.stderr)
        sys.exit(1)

    from reporter.generator import Reporter
    db_conn = DbConnection(arch_dir / "arch.db")
    repository = Repository(db_conn)

    reporter = Reporter(repository)
    try:
        report_text = reporter.generate_report(args.name, args.format)
        print(report_text)
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db_conn.close()


def cmd_set_status(args):
    """Sets manual AI compliance status flag for a file."""
    project_root = Path(args.project_root).resolve()
    arch_dir = project_root / ".arch"
    if not arch_dir.exists():
        print("Error: Workspace not initialized. Run 'arch init' first.", file=sys.stderr)
        sys.exit(1)

    db_conn = DbConnection(arch_dir / "arch.db")
    repository = Repository(db_conn)

    status = args.status.upper()
    if status not in ("COMPLIANT", "VIOLATION_DETECTED"):
        print(f"Error: Invalid manual compliance status choice: {args.status}. Allowed: COMPLIANT, VIOLATION_DETECTED.", file=sys.stderr)
        sys.exit(1)

    if status == "VIOLATION_DETECTED" and not args.justification:
        print("Error: Justification must be provided when flagging a file as VIOLATION_DETECTED.", file=sys.stderr)
        sys.exit(1)

    try:
        filepath = args.filepath
        file_info = repository.files.get_file(filepath)
        if not file_info:
            all_files = repository.files.get_all_files_metadata()
            matched = None
            for fp in all_files.keys():
                if fp.replace("\\", "/").endswith(filepath.replace("\\", "/")):
                    matched = fp
                    break
            if matched:
                filepath = matched
                file_info = repository.files.get_file(filepath)
                
        if not file_info:
            print(f"Error: File '{args.filepath}' is not registered in the database.", file=sys.stderr)
            sys.exit(1)

        # 1. Update manual_status in files table
        repository.files.update_file_manual_status(filepath, status, args.justification)
        
        # 2. Sync manual violations in compliance_violations table
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
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db_conn.close()


def cmd_set_fields(args):
    """Sets manual fields for a file."""
    project_root = Path(args.project_root).resolve()
    arch_dir = project_root / ".arch"
    if not arch_dir.exists():
        print("Error: Workspace not initialized. Run 'arch init' first.", file=sys.stderr)
        sys.exit(1)

    db_conn = DbConnection(arch_dir / "arch.db")
    repository = Repository(db_conn)

    import json
    try:
        fields = json.loads(args.fields_json)
    except Exception as e:
        print(f"Error: Invalid JSON fields payload: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        filepath = args.filepath
        file_info = repository.files.get_file(filepath)
        if not file_info:
            all_files = repository.files.get_all_files_metadata()
            matched = None
            for fp in all_files.keys():
                if fp.replace("\\", "/").endswith(filepath.replace("\\", "/")):
                    matched = fp
                    break
            if matched:
                filepath = matched
                file_info = repository.files.get_file(filepath)
                
        if not file_info:
            print(f"Error: File '{args.filepath}' is not registered in the database.", file=sys.stderr)
            sys.exit(1)

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
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db_conn.close()
def cmd_clear_pending(args):
    """Clears all pending audit flags in the database."""
    project_root = Path(args.project_root).resolve()
    arch_dir = project_root / ".arch"
    if not arch_dir.exists():
        print("Error: Workspace not initialized. Run 'arch init' first.", file=sys.stderr)
        sys.exit(1)

    db_conn = DbConnection(arch_dir / "arch.db")
    repository = Repository(db_conn)

    try:
        repository.files.clear_all_pending_audits(args.justification)
        # Run audit to update violations
        auditor = Auditor(repository, project_root)
        auditor.run_audit()
        print("Successfully cleared pending audit status for all files.")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db_conn.close()



def main():
    parser = argparse.ArgumentParser(
        prog="arch",
        description="Arch-mcp: Agent-Native Code Intelligence & Compliance Engine"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # init (unified setup + indexer)
    init_parser = subparsers.add_parser("init", help="Initialize workspace, download models, and index symbols")
    init_parser.add_argument("project_root", nargs="?", default=".", help="Project root directory")
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

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
