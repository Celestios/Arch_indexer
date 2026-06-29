import tempfile
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from engines.codeql_wrapper import CodeQlWrapper


@dataclass
class FfiSurface:
    symbol_name: str
    signature: str
    filepath: str
    language: str


class FfiExtractor:
    """
    Uses CodeQL to extract FFI entry points from source code.
    Language-agnostic: runs per-language CodeQL queries and normalizes results.
    Composes CodeQlWrapper for all CodeQL CLI interaction.
    """

    QUERIES_DIR = Path(__file__).parent / "ffi_queries"

    def __init__(self, codeql_wrapper: Optional["CodeQlWrapper"] = None):
        self.codeql = codeql_wrapper

    def extract_all(self, project_root: Path, languages: Optional[List[str]] = None) -> List[FfiSurface]:
        if not self.codeql or not self.codeql.is_available():
            print("[FFI Extract] CodeQL not available, skipping FFI extraction.")
            return []

        if languages is None:
            languages = ["rust", "dart"]

        all_surfaces: List[FfiSurface] = []
        for lang in languages:
            if lang == "rust":
                all_surfaces.extend(self.extract_rust_ffi(project_root))
            elif lang == "dart":
                all_surfaces.extend(self.extract_dart_ffi(project_root))

        print(f"[FFI Extract] Found {len(all_surfaces)} FFI surfaces across {len(languages)} languages.")
        return all_surfaces

    def extract_rust_ffi(self, project_root: Path) -> List[FfiSurface]:
        return self._run_ffi_query(project_root, "rust", "rust_ffi.ql")

    def extract_dart_ffi(self, project_root: Path) -> List[FfiSurface]:
        return self._run_ffi_query(project_root, "dart", "dart_ffi.ql")

    def _run_ffi_query(self, project_root: Path, language: str, query_file: str) -> List[FfiSurface]:
        ql_path = self.QUERIES_DIR / query_file
        if not ql_path.exists():
            print(f"[FFI Extract] Query file not found: {ql_path}")
            return []

        arch_dir = project_root / ".arch"
        db_dir = arch_dir / "codeql_db"
        if not db_dir.exists():
            print(f"[FFI Extract] No CodeQL database found at {db_dir}, skipping {language} FFI extraction.")
            return []

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            bqrs_file = temp_path / "ffi_results.bqrs"
            json_file = temp_path / "ffi_results.json"

            try:
                if not self.codeql.run_query(db_dir, ql_path, bqrs_file):
                    print(f"[FFI Extract] CodeQL query failed for {language}.")
                    return []
            except RuntimeError:
                print(f"[FFI Extract] CodeQL not available for {language} query.")
                return []

            try:
                data = self.codeql.decode_bqrs(bqrs_file, json_file)
                if data and "tuples" in data:
                    return self._parse_query_results(data["tuples"], language)
            except RuntimeError:
                print(f"[FFI Extract] CodeQL not available to decode BQRS for {language}.")

        return []

    def _parse_query_results(self, tuples: list, language: str) -> List[FfiSurface]:
        surfaces = []
        for row in tuples:
            if len(row) >= 3:
                name = row[0].get("value", "") if isinstance(row[0], dict) else str(row[0])
                sig = row[1].get("value", "") if isinstance(row[1], dict) else str(row[1])
                fp = row[2].get("value", "") if isinstance(row[2], dict) else str(row[2])
                if name:
                    surfaces.append(FfiSurface(
                        symbol_name=name,
                        signature=sig,
                        filepath=fp,
                        language=language
                    ))
        return surfaces
