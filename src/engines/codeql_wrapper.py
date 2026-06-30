import sys
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Any, Optional

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
            res = subprocess.run([str(self.codeql_exe), "--version"], capture_output=True, text=True, shell=(sys.platform == "win32"))
            return res.returncode == 0
        except Exception:
            return False

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
            f"--source-root={source_root}"
        ]

        if build_command:
            cmd.append(f"--command={build_command}")
        elif language == "rust":
            if (source_root / "Cargo.toml").exists():
                cmd.append('--command=cargo build')
            else:
                cargo_files = [p for p in source_root.glob("**/Cargo.toml") if "target" not in p.parts and ".venv" not in p.parts and ".arch" not in p.parts]
                if cargo_files:
                    rel_path = cargo_files[0].relative_to(source_root)
                    manifest_path = str(rel_path).replace("\\", "/")
                    cmd.append(f'--command=cargo build --manifest-path {manifest_path}')
                else:
                    cmd.append('--command=cargo build')

        print(f"[CodeQL] Creating database at {db_output_dir} for {language}...")
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True, shell=(sys.platform == "win32"))
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

        # Write changed files list to temp file
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write('\n'.join(changed_files))
            changes_file = f.name

        try:
            cmd = [
                str(self.codeql_exe),
                "database",
                "init",
                str(db_output_dir),
                f"--overlay-base={base_db_dir}",
                f"--overlay-changes={changes_file}",
                f"--source-root={source_root}"
            ]

            subprocess.run(cmd, capture_output=True, text=True, check=True, shell=(sys.platform == "win32"))
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
        if not self.is_available():
            raise RuntimeError(
                f"CodeQL CLI not working at `{self.codeql_exe}`. "
                f"Verify the executable exists and `codeql --version` runs successfully."
            )

        if bqrs_output.exists():
            bqrs_output.unlink()

        # Search path - point to the ql directory which contains both lib and src
        source_root = self.bin_dir.parent
        search_path = str(source_root / "codeql" / "rust" / "ql")

        cmd = [
            str(self.codeql_exe),
            "query",
            "run",
            str(ql_file),
            f"--database={db_dir}",
            f"--output={bqrs_output}",
            f"--search-path={search_path}"
        ]

        print(f"[CodeQL] Running query {ql_file.name} against database...")
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True, shell=(sys.platform == "win32"))
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
            subprocess.run(cmd, capture_output=True, text=True, check=True, shell=(sys.platform == "win32"))
            if json_output.exists():
                with open(json_output, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            print(f"Error decoding BQRS file: {e}", file=sys.stderr)
            
        return None

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
