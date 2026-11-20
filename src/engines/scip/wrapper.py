import shutil
from pathlib import Path
from typing import Dict, List, Any, Optional

from utils.exclusions import load_include_dirs, is_included
from engines.registry import LanguageRegistry
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

    _SPECIALIZED_INDEXERS = {
        "dart": index_dart,
        "rust": index_rust,
        "python": index_python,
    }

    @staticmethod
    def _move_index_to_arch(project_dir: Path, language: str, cargo_root: Path = None) -> Optional[Path]:
        """Move generated index.scip to .arch/index_{language}.scip."""
        return _move_index_to_arch(project_dir, language, cargo_root)

    @classmethod
    def detect_languages(cls, project_dir: Path) -> List[str]:
        """Detects languages present in the project using LanguageRegistry manifests and extensions."""
        languages: List[str] = []
        include_dirs = load_include_dirs(project_dir)

        def _is_path_included(p: Path) -> bool:
            return include_dirs is None or is_included(str(p.relative_to(project_dir)), include_dirs)

        # Candidates with SCIP support
        scip_candidate_order = ["dart", "rust", "go", "typescript", "java", "python"]
        for lang in LanguageRegistry.list_languages():
            if lang not in scip_candidate_order:
                spec = LanguageRegistry.get_spec(lang)
                if spec and spec.scip_binary and lang != "javascript":
                    scip_candidate_order.append(lang)

        for lang in scip_candidate_order:
            spec = LanguageRegistry.get_spec(lang)
            if not spec:
                continue

            detected = False
            # 1. Check primary manifests at project root
            for manifest in spec.manifest_names:
                if (project_dir / manifest).exists():
                    detected = True
                    break

            # 2. Check recursive manifests (excluding standard build/cache artifacts)
            if not detected and spec.manifest_names:
                for manifest in spec.manifest_names:
                    for p in project_dir.rglob(manifest):
                        p_str = str(p).replace("\\", "/")
                        if any(skip in p_str for skip in (".dart_tool", "dart_analyzer", "/target/", "/.arch/", "/node_modules/", "/.git/")):
                            continue
                        if _is_path_included(p):
                            detected = True
                            break
                    if detected:
                        break

            # 3. Check source file extensions under include_dirs
            if not detected and spec.extensions:
                for ext in spec.extensions:
                    pattern = f"**/*{ext}"
                    for p in project_dir.glob(pattern):
                        p_str = str(p).replace("\\", "/")
                        if any(skip in p_str for skip in (".dart_tool", "/target/", "/.arch/", "/node_modules/", "/.git/", "/__pycache__/")):
                            continue
                        if _is_path_included(p):
                            detected = True
                            break
                    if detected:
                        break

            if detected and lang not in languages:
                languages.append(lang)

        return languages

    @classmethod
    def verify_environment(cls, languages: List[str]) -> Dict[str, bool]:
        """Checks if the required toolchains are installed and available."""
        status: Dict[str, bool] = {}
        for lang in languages:
            spec = LanguageRegistry.get_spec(lang)
            if lang == "rust":
                has_rustup = shutil.which("rustup") is not None
                has_ra = shutil.which("rust-analyzer") is not None
                status["rust"] = has_rustup or has_ra
            elif spec and spec.scip_binary:
                status[lang] = shutil.which(spec.scip_binary) is not None
            elif spec and spec.tool_names:
                status[lang] = any(shutil.which(tool) is not None for tool in spec.tool_names)
            else:
                status[lang] = False
        return status

    @classmethod
    def run_indexer(cls, project_dir: Path, language: str) -> Optional[Path]:
        """
        Executes the language-specific SCIP indexer and returns the path to the generated index.scip.
        Queries LanguageRegistry for toolchain availability.
        """
        if language in cls._SPECIALIZED_INDEXERS:
            return cls._SPECIALIZED_INDEXERS[language](project_dir)

        spec = LanguageRegistry.get_spec(language)
        if spec and (spec.scip_binary or language in ("go", "typescript", "java")):
            return index_generic(project_dir, language)

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
