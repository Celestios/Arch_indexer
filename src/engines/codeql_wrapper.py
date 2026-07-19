import sys
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Any, Optional

from utils.exclusions import load_include_dirs, is_included

DEFAULT_SUBPROCESS_TIMEOUT = 600


class CodeQlWrapper:
    """
    Wrapper for GitHub CodeQL CLI.
    Orchestrates CodeQL database creation, query execution, and BQRS results decoding.
    """

    def __init__(self, bin_dir: Path):
        """Initializes the wrapper and locates the local codeql.exe executable."""
        self.bin_dir = bin_dir
        self.codeql_exe = bin_dir / "codeql" / "codeql.exe"
        
        # Fallback to checking the system path if local executable is missing
        if not self.codeql_exe.exists():
            system_path = shutil.which("codeql")
            if system_path:
                self.codeql_exe = Path(system_path)

    def is_available(self) -> bool:
        """Returns True if the CodeQL CLI executable is resolved and working."""
        if not self.codeql_exe or not self.codeql_exe.exists():
            return False
        try:
            res = subprocess.run([str(self.codeql_exe), "--version"], capture_output=True, text=True, encoding='utf-8', errors='replace', shell=(sys.platform == "win32"), timeout=30)
            return res.returncode == 0
        except Exception:
            return False

    def _resolve_rust_build_command(self, source_root: Path) -> str:
        """Resolve the Rust build command, detecting Cargo.toml location."""
        if (source_root / "Cargo.toml").exists():
            return 'cargo build'
        include_dirs = load_include_dirs(source_root)
        cargo_files = [p for p in source_root.glob("**/Cargo.toml")
                      if include_dirs is None or is_included(str(p.relative_to(source_root)), include_dirs)]
        if cargo_files:
            rel_path = cargo_files[0].relative_to(source_root)
            manifest_path = str(rel_path).replace("\\", "/")
            return f'cargo build --manifest-path {manifest_path}'
        return 'cargo build'

    def create_database(
        self,
        source_root: Path,
        db_output_dir: Path,
        language: str,
        build_command: Optional[str] = None,
        changed_files: Optional[List[str]] = None
    ) -> bool:
        """
        Creates a CodeQL database of the codebase at source_root.
        If changed_files is provided and a base database exists, uses overlay mode.
        Otherwise creates a full database with --overlay-base for future incremental updates.
        """
        if not self.is_available():
            raise RuntimeError("CodeQL CLI is not available. Please verify installation.")

        base_db_dir = db_output_dir.parent / f"{db_output_dir.name}_base"
        use_overlay = changed_files and base_db_dir.exists()

        if use_overlay:
            return self._create_overlay_database(source_root, db_output_dir, base_db_dir, language, changed_files)

        # Full database creation
        if db_output_dir.exists():
            shutil.rmtree(db_output_dir)

        cmd = [
            str(self.codeql_exe),
            "database",
            "create",
            str(db_output_dir),
            f"--language={language}",
            f"--source-root={source_root}",
            "--overlay-base"
        ]

        if build_command:
            cmd.append(f"--command={build_command}")
        elif language == "rust":
            cmd.append(f'--command={self._resolve_rust_build_command(source_root)}')

        print(f"[CodeQL] Creating database at {db_output_dir} for {language}...")
        try:
            subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', check=True, shell=(sys.platform == "win32"), timeout=DEFAULT_SUBPROCESS_TIMEOUT)
            # Save as base for future overlay runs
            if base_db_dir.exists():
                shutil.rmtree(base_db_dir)
            shutil.copytree(str(db_output_dir), str(base_db_dir))
            print("[CodeQL] Database created successfully.")
            return True
        except subprocess.CalledProcessError as e:
            print(f"Error creating CodeQL database: {e.stderr}", file=sys.stderr)
            return False

    def _create_overlay_database(
        self,
        source_root: Path,
        db_output_dir: Path,
        base_db_dir: Path,
        language: str,
        changed_files: List[str]
    ) -> bool:
        """Create an overlay database on top of the base, processing only changed files."""
        print(f"[CodeQL] Creating overlay database for {len(changed_files)} changed files...")

        # Write changed files list to temp JSON file
        import tempfile
        import json
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"changes": changed_files}, f)
            changes_file = f.name

        try:
            # 1. Copy base database to output directory first
            if db_output_dir.exists():
                shutil.rmtree(db_output_dir)
            shutil.copytree(str(base_db_dir), str(db_output_dir))

            # 2. Run database init
            cmd_init = [
                str(self.codeql_exe),
                "database",
                "init",
                f"--overlay-changes={changes_file}",
                f"--source-root={source_root}",
                f"--language={language}",
                str(db_output_dir)
            ]
            subprocess.run(cmd_init, capture_output=True, text=True, encoding='utf-8', errors='replace', check=True, shell=(sys.platform == "win32"), timeout=DEFAULT_SUBPROCESS_TIMEOUT)

            # 3. Determine build command for compiler tracing
            build_command = None
            if language == "rust":
                build_command = self._resolve_rust_build_command(source_root)

            # 4. Run trace-command (compile changes)
            if build_command:
                cmd_trace = [
                    str(self.codeql_exe),
                    "database",
                    "trace-command",
                    str(db_output_dir),
                    "--",
                ] + build_command.split()
                subprocess.run(cmd_trace, capture_output=True, text=True, encoding='utf-8', errors='replace', check=True, shell=(sys.platform == "win32"), timeout=DEFAULT_SUBPROCESS_TIMEOUT)

            # 5. Finalize the overlay database
            cmd_finalize = [
                str(self.codeql_exe),
                "database",
                "finalize",
                str(db_output_dir)
            ]
            subprocess.run(cmd_finalize, capture_output=True, text=True, encoding='utf-8', errors='replace', check=True, shell=(sys.platform == "win32"), timeout=DEFAULT_SUBPROCESS_TIMEOUT)

            print("[CodeQL] Overlay database created successfully.")
            return True
        except subprocess.CalledProcessError as e:
            print(f"[CodeQL] Overlay failed, falling back to full: {e.stderr}", file=sys.stderr)
            return self.create_database(source_root, db_output_dir, language)
        finally:
            import os
            os.unlink(changes_file)

    def run_query(self, db_dir: Path, ql_file: Path, bqrs_output: Path) -> bool:
        """
        Executes a single QL query against the database, outputting binary BQRS results.
        """
        import shutil
        import sys

        if not self.is_available():
            raise RuntimeError(
                f"CodeQL CLI not working at `{self.codeql_exe}`. "
                f"Verify the executable exists and `codeql --version` runs successfully."
            )

        if bqrs_output.exists():
            bqrs_output.unlink()

        # 1. Setup workspace queries directory
        workspace_queries = db_dir.parent / "codeql_queries" / ql_file.parent.name
        workspace_queries.mkdir(parents=True, exist_ok=True)

        # 2. Copy the QL query file to workspace
        workspace_ql_file = workspace_queries / ql_file.name
        shutil.copy(ql_file, workspace_ql_file)

        # 3. Create qlpack.yml if it doesn't exist
        qlpack_file = workspace_queries / "qlpack.yml"
        if not qlpack_file.exists():
            lang_dep = "codeql/rust-all"
            if ql_file.name.startswith("dart"):
                lang_dep = "codeql/dart-all"
            elif ql_file.name.startswith("go"):
                lang_dep = "codeql/go-all"
            elif ql_file.name.startswith("java"):
                lang_dep = "codeql/java-all"
            elif ql_file.name.startswith("python"):
                lang_dep = "codeql/python-all"
            
            with open(qlpack_file, "w", encoding="utf-8") as f:
                f.write(f"name: arch-{ql_file.stem.replace('_', '-')}\n")
                f.write("version: 1.0.0\n")
                f.write("dependencies:\n")
                f.write(f"  {lang_dep}: \"*\"\n")

        # 4. Install pack dependencies
        pkg_lock = workspace_queries / "codeql-pack.lock.yml"
        if not pkg_lock.exists():
            print(f"[CodeQL] Installing query dependencies for {ql_file.name}...")
            res = subprocess.run(
                [str(self.codeql_exe), "pack", "install"],
                cwd=str(workspace_queries),
                shell=(sys.platform == "win32"),
                capture_output=True,
                text=True,
                timeout=DEFAULT_SUBPROCESS_TIMEOUT
            )
            if res.returncode != 0:
                print(f"[CodeQL] Warning: codeql pack install failed: {res.stderr}", file=sys.stderr)

        # 5. Execute the query
        cmd = [
            str(self.codeql_exe),
            "query",
            "run",
            str(workspace_ql_file),
            f"--database={db_dir}",
            f"--output={bqrs_output}"
        ]

        print(f"[CodeQL] Running query {ql_file.name} against database...")
        try:
            subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', check=True, shell=(sys.platform == "win32"), timeout=DEFAULT_SUBPROCESS_TIMEOUT)
            return bqrs_output.exists()
        except subprocess.CalledProcessError as e:
            print(f"Error running CodeQL query: {e.stderr}", file=sys.stderr)
            return False

    def decode_bqrs(self, bqrs_file: Path, json_output: Path) -> Optional[Dict[str, Any]]:
        """
        Decodes a binary BQRS results file into JSON format.
        """
        if not self.is_available():
            raise RuntimeError("CodeQL CLI is not available.")

        if json_output.exists():
            json_output.unlink()

        cmd = [
            str(self.codeql_exe),
            "bqrs",
            "decode",
            str(bqrs_file),
            "--format=json",
            f"--output={json_output}"
        ]

        try:
            subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', check=True, shell=(sys.platform == "win32"), timeout=DEFAULT_SUBPROCESS_TIMEOUT)
            if json_output.exists():
                with open(json_output, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            print(f"Error decoding BQRS file: {e}", file=sys.stderr)

        return None

    def extract_kinds(self, db_dir: Path, language: str) -> List[Dict[str, Any]]:
        """
        Runs a CodeQL kind-extraction query against the database.
        Returns a list of dicts with keys: name, kind, file, line.
        """
        queries_dir = Path(__file__).parent / "queries"
        query_file = queries_dir / f"{language}_kinds.ql"

        if not query_file.exists():
            return []

        import tempfile
        with tempfile.TemporaryDirectory() as temp_dir:
            bqrs_file = Path(temp_dir) / "kinds.bqrs"
            json_file = Path(temp_dir) / "kinds.json"

            if not self.run_query(db_dir, query_file, bqrs_file):
                return []

            data = self.decode_bqrs(bqrs_file, json_file)
            if not data or "#select" not in data:
                return []

            kinds = []
            for row in data["#select"].get("tuples", []):
                if len(row) >= 4:
                    name, kind, file, line = row[0], row[1], row[2], row[3]
                    if name and kind:
                        kinds.append({"name": name, "kind": kind, "file": file, "line": line})
            return kinds

    def trace_data_flow(
        self,
        db_dir: Path,
        source_symbol: str,
        sink_symbol: str,
        language: str = "rust"
    ) -> List[Dict[str, Any]]:
        """
        Generates and runs a dynamic data flow query to trace variables between two symbols.
        Returns the data-flow path steps.
        """
        if not self.is_available():
            raise RuntimeError(
                f"CodeQL CLI not working at `{self.codeql_exe}`. "
                f"Verify the executable exists and `codeql --version` runs successfully."
            )

        # Place query inside the existing qlpack so modules can be resolved
        source_root = self.bin_dir.parent
        query_dir = source_root / "codeql" / "rust" / "ql" / "src" / "queries" / "arch_trace"
        query_dir.mkdir(parents=True, exist_ok=True)

        ql_file = query_dir / "flow.ql"
        bqrs_file = query_dir / "flow.bqrs"
        json_file = query_dir / "flow.json"

        # Generate the QL code dynamically based on source/sink symbols
        ql_code = f"""import rust

from Element e
where e.toString() = "{source_symbol}" or e.toString() = "{sink_symbol}"
select e, "Found symbol"
"""
        ql_file.write_text(ql_code, encoding="utf-8")

        # Run the query and decode results
        try:
            if self.run_query(db_dir, ql_file, bqrs_file):
                results = self.decode_bqrs(bqrs_file, json_file)
                if results and "tuples" in results:
                    return results["tuples"]
        finally:
            # Clean up generated files
            for f in [ql_file, bqrs_file, json_file]:
                if f.exists():
                    f.unlink()

        return []
