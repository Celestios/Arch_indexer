import tempfile
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from engines.codeql_wrapper import CodeQlWrapper
    from engines.dart_analyzer import DartAnalyzerWrapper


@dataclass
class FfiSurface:
    symbol_name: str
    signature: str
    filepath: str
    language: str


class FfiExtractor:
    """
    Language-agnostic FFI entry point extractor.

    Supports multiple backends per language:
    - DartAnalyzer: For .dart files (preferred when available)
    - CodeQL: For languages with databases (rust, go, java, etc.)

    Usage:
        extractor = FfiExtractor(
            codeql_wrappers={"rust": codeql_rust, "go": codeql_go},
            dart_analyzer=dart_analyzer
        )
        surfaces = extractor.extract_all(project_root, languages=["dart", "rust", "go"])
    """

    QUERIES_DIR = Path(__file__).parent / "ffi_queries"

    def __init__(self, codeql_wrappers: Optional[Dict[str, "CodeQlWrapper"]] = None,
                 dart_analyzer: Optional["DartAnalyzerWrapper"] = None,
                 # Backward compatibility: accept single codeql_wrapper
                 codeql_wrapper: Optional["CodeQlWrapper"] = None):
        # Support both old (single) and new (dict) patterns
        if codeql_wrappers is not None:
            self.codeql_wrappers = codeql_wrappers
        elif codeql_wrapper is not None:
            # Convert single wrapper to dict with "generic" key
            self.codeql_wrappers = {"generic": codeql_wrapper}
        else:
            self.codeql_wrappers = {}

        self.dart_analyzer = dart_analyzer

    def _get_codeql_for_language(self, language: str) -> Optional["CodeQlWrapper"]:
        """Get the CodeQL wrapper for a specific language."""
        # Try language-specific wrapper first
        if language in self.codeql_wrappers:
            wrapper = self.codeql_wrappers[language]
            if wrapper and wrapper.is_available():
                return wrapper

        # Fall back to generic wrapper
        if "generic" in self.codeql_wrappers:
            wrapper = self.codeql_wrappers["generic"]
            if wrapper and wrapper.is_available():
                return wrapper

        return None

    def extract_all(self, project_root: Path, languages: Optional[List[str]] = None) -> List[FfiSurface]:
        """
        Extract FFI surfaces from all specified languages.
        Language-agnostic: uses appropriate backend for each language.
        """
        if languages is None:
            languages = ["rust", "dart"]

        all_surfaces: List[FfiSurface] = []

        for lang in languages:
            all_surfaces.extend(self._extract_language_ffi(project_root, lang))

        print(f"[FFI Extract] Found {len(all_surfaces)} FFI surfaces across {len(languages)} languages.")
        return all_surfaces

    def _extract_language_ffi(self, project_root: Path, language: str) -> List[FfiSurface]:
        """Extract FFI surfaces for a specific language using best available backend."""
        # Special handling for Dart (prefer analyzer)
        if language == "dart":
            return self._extract_dart_ffi(project_root)

        # For other languages, use CodeQL
        codeql = self._get_codeql_for_language(language)
        if codeql:
            return self._extract_with_codeql(project_root, language, codeql)

        print(f"[FFI Extract] No backend available for {language} FFI extraction.")
        return []

    def _extract_dart_ffi(self, project_root: Path) -> List[FfiSurface]:
        """Extract Dart FFI surfaces using best available backend."""
        # Prefer dart_analyzer if available
        if self.dart_analyzer and self.dart_analyzer.is_available():
            print("[FFI Extract] Using Dart analyzer for FFI detection.")
            return self.dart_analyzer.detect_ffi()

        # Fall back to CodeQL
        codeql = self._get_codeql_for_language("dart")
        if codeql:
            print("[FFI Extract] Using CodeQL for Dart FFI detection.")
            return self._extract_with_codeql(project_root, "dart", codeql)

        print("[FFI Extract] No backend available for Dart FFI extraction.")
        return []

    def _extract_with_codeql(self, project_root: Path, language: str,
                             codeql: "CodeQlWrapper") -> List[FfiSurface]:
        """Extract FFI surfaces using CodeQL for a specific language."""
        # Check for language-specific query file
        query_file = f"{language}_ffi.ql"
        ql_path = self.QUERIES_DIR / query_file

        if not ql_path.exists():
            print(f"[FFI Extract] Query file not found: {ql_path}")
            return []

        arch_dir = project_root / ".arch"
        # Check for language-specific database first
        db_dir = arch_dir / f"codeql_db_{language}"
        if not db_dir.exists():
            db_dir = arch_dir / "codeql_db"
        if not db_dir.exists():
            print(f"[FFI Extract] No CodeQL database found for {language}, skipping.")
            return []

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            bqrs_file = temp_path / "ffi_results.bqrs"
            json_file = temp_path / "ffi_results.json"

            try:
                if not codeql.run_query(db_dir, ql_path, bqrs_file):
                    print(f"[FFI Extract] CodeQL query failed for {language}.")
                    return []
            except RuntimeError:
                print(f"[FFI Extract] CodeQL not available for {language} query.")
                return []

            try:
                data = codeql.decode_bqrs(bqrs_file, json_file)
                if data and "tuples" in data:
                    return self._parse_query_results(data["tuples"], language)
            except RuntimeError:
                print(f"[FFI Extract] CodeQL not available to decode BQRS for {language}.")

        return []

    # Public API methods (backward compatible)
    def extract_rust_ffi(self, project_root: Path) -> List[FfiSurface]:
        """Public API: Extract Rust FFI surfaces."""
        return self._extract_language_ffi(project_root, "rust")

    def extract_dart_ffi(self, project_root: Path) -> List[FfiSurface]:
        """Public API: Extract Dart FFI surfaces."""
        return self._extract_dart_ffi(project_root)

    def _parse_query_results(self, tuples: list, language: str) -> List[FfiSurface]:
        """Parse BQRS tuple results into FfiSurface objects."""
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
