import sys
import argparse
from pathlib import Path

from setup.initializer import initialize_workspace
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
    """Unified setup command: initialize workspace, prompt for ONNX embedder, and build code index."""
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

    # 3. Initialize workspace structure & DB
    arch_dir = initialize_workspace(project_root)
    print(f"\nWorkspace folder initialized at {arch_dir}")

    # 4. Bootstrap ONNX model if requested
    embedder = None
    if choice != "4":
        print("\n--- Downloading ONNX Model Assets ---")
        try:
            from setup.embedder_bootstrap import bootstrap_onnx_model, EMBEDDING_MODELS
            bin_dir = Path(__file__).resolve().parent.parent / "bin"
            target_models_dir = bin_dir / "models"
            
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
                ScipWrapper.ingest_index(repository, parsed, embedder)
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

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
