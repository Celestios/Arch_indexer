import shutil
from pathlib import Path
from typing import Dict, List, Any, Optional

from utils.exclusions import load_include_dirs, is_included
from engines.scip.indexers import (
    index_rust, index_dart, index_python, index_generic, _move_index_to_arch
)
from engines.scip.parser import ScipParser
from engines.scip.ingester import IndexIngester


class ScipWrapper:
    """
    Wrapper for SCIP/LSIF code graph generators and parsers.
    Handles Dart/Flutter and Rust toolchain indexing and extracts normalized symbols & edges.
    """

    @staticmethod
    def _move_index_to_arch(project_dir: Path, language: str, cargo_root: Path = None) -> Optional[Path]:
        """Move generated index.scip to .arch/index_{language}.scip."""
        return _move_index_to_arch(project_dir, language, cargo_root)

    @staticmethod
    def detect_languages(project_dir: Path) -> List[str]:
        """Detects if the project contains Dart/Flutter, Rust, Go, TypeScript/JavaScript, Java, or Python source files."""
        languages = []

        if (project_dir / "pubspec.yaml").exists():
            languages.append("dart")
        elif any(p.parent != project_dir for p in project_dir.rglob("pubspec.yaml")
                 if ".dart_tool" not in str(p) and "dart_analyzer" not in str(p)):
            languages.append("dart")
        if (project_dir / "Cargo.toml").exists():
            languages.append("rust")
        elif any(p.parent != project_dir for p in project_dir.rglob("Cargo.toml")
                 if "target" not in str(p) and ".arch" not in str(p)):
            languages.append("rust")
        if (project_dir / "go.mod").exists():
            languages.append("go")
        if (project_dir / "package.json").exists():
            languages.append("typescript")
        if (project_dir / "pom.xml").exists() or (project_dir / "build.gradle").exists():
            languages.append("java")

        include_dirs = load_include_dirs(project_dir)
        def _filtered_glob(pattern):
            for p in project_dir.glob(pattern):
                if include_dirs is None or is_included(str(p.relative_to(project_dir)), include_dirs):
                    yield p

        if any(_filtered_glob("**/requirements.txt")) or any(_filtered_glob("**/*.py")):
            languages.append("python")
        return languages

    @staticmethod
    def verify_environment(languages: List[str]) -> Dict[str, bool]:
        """Checks if the required toolchains are installed and available."""
        status = {}
        if "dart" in languages:
            status["dart"] = shutil.which("dart") is not None

        if "rust" in languages:
            has_rustup = shutil.which("rustup") is not None
            has_ra = shutil.which("rust-analyzer") is not None
            status["rust"] = has_rustup or has_ra

        if "go" in languages:
            status["go"] = shutil.which("scip-go") is not None

        if "typescript" in languages:
            status["typescript"] = shutil.which("scip-typescript") is not None

        if "java" in languages:
            status["java"] = shutil.which("scip-java") is not None

        if "python" in languages:
            status["python"] = shutil.which("scip-python") is not None

        return status

    @staticmethod
    def run_indexer(project_dir: Path, language: str) -> Optional[Path]:
        """
        Executes the language-specific SCIP indexer and returns the path to the generated index.scip.
        """
        handlers = {
            "dart": index_dart,
            "rust": index_rust,
            "go": index_generic,
            "typescript": index_generic,
            "java": index_generic,
            "python": index_python,
        }
        handler = handlers.get(language)
        if handler:
            if language in ("go", "typescript", "java"):
                return handler(project_dir, language)
            return handler(project_dir)
        return None

    @staticmethod
    def parse_index(
        scip_file: Path,
        project_root: Optional[Path] = None,
        changed_files: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Parses a binary index.scip file into a normalized dictionary
        of symbols, occurrences, and edges.
        Filters by include_dirs from config.json if project_root is provided.
        Filters by changed_files to skip disk I/O and occurrences for unchanged files.
        """
        return ScipParser.parse_index(scip_file, project_root, changed_files=changed_files)

    @staticmethod
    def ingest_index(repository, parsed_data, project_root=None, force=False, config=None):
        """
        Ingests the parsed symbols, occurrences, and edges into the database.
        Uses incremental ingestion: only processes files whose content has changed.

        The `config` parameter is retained for API compatibility; edge weights are
        now computed during the audit phase (see EdgeWeightUpdater).
        """
        return IndexIngester.ingest_index(
            repository, parsed_data, project_root, force, config
        )
