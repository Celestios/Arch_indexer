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
            res = subprocess.run([str(self.codeql_exe), "--version"], capture_output=True, text=True)
            return res.returncode == 0
        except Exception:
            return False

    def create_database(
        self,
        source_root: Path,
        db_output_dir: Path,
        language: str,
        build_command: Optional[str] = None
    ) -> bool:
        """
        Creates a CodeQL database of the codebase at source_root.
        """
        if not self.is_available():
            raise RuntimeError("CodeQL CLI is not available. Please verify installation.")

        # Ensure output directory doesn't already exist (CodeQL requires it to be empty/new)
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

        # For compiled languages like Rust or C++, we must pass a build command
        if build_command:
            cmd.append(f"--command={build_command}")
        elif language == "rust":
            cmd.append('--command=cargo build')

        print(f"[CodeQL] Creating database at {db_output_dir} for {language}...")
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            print("[CodeQL] Database created successfully.")
            return True
        except subprocess.CalledProcessError as e:
            print(f"Error creating CodeQL database: {e.stderr}", file=sys.stderr)
            return False

    def run_query(self, db_dir: Path, ql_file: Path, bqrs_output: Path) -> bool:
        """
        Executes a single QL query against the database, outputting binary BQRS results.
        """
        if not self.is_available():
            raise RuntimeError("CodeQL CLI is not available.")

        if bqrs_output.exists():
            bqrs_output.unlink()

        cmd = [
            str(self.codeql_exe),
            "query",
            "run",
            str(ql_file),
            f"--database={db_dir}",
            f"--output={bqrs_output}"
        ]

        print(f"[CodeQL] Running query {ql_file.name} against database...")
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
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
            subprocess.run(cmd, capture_output=True, text=True, check=True)
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
        # Create a temp directory to compile the query on-the-fly
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            ql_file = temp_path / "flow.ql"
            bqrs_file = temp_path / "flow.bqrs"
            json_file = temp_path / "flow.json"

            # 1. Generate the QL code dynamically based on source/sink symbols
            # Note: This is a placeholder query structure. Real implementations will
            # target the language's specific standard data-flow libraries.
            ql_code = f"""
            import {language}
            import codeql.{language}.dataflow.DataFlow

            // Parameterized query looking for flow between specified symbols
            from DataFlow::Node source, DataFlow::Node sink
            where 
              source.toString() = "{source_symbol}" and
              sink.toString() = "{sink_symbol}" and
              DataFlow::localFlow(source, sink)
            select source, sink, "Path resolved from {source_symbol} to {sink_symbol}"
            """
            ql_file.write_text(ql_code, encoding="utf-8")

            # 2. Run the query and decode results
            if self.run_query(db_dir, ql_file, bqrs_file):
                results = self.decode_bqrs(bqrs_file, json_file)
                if results and "tuples" in results:
                    return results["tuples"]

        return []
