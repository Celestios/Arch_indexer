import shutil
from pathlib import Path
from typing import Dict, List

from engines.registry import LanguageRegistry
from engines.scip.indexers import _move_index_to_arch, run_indexer
from engines.scip.ingester import ingest_index
from engines.scip.parser import parse_index
from utils.exclusions import DEFAULT_EXCLUDED_DIRS, is_included, load_include_dirs


def _has_excluded_part(p: Path) -> bool:
    return any(part in DEFAULT_EXCLUDED_DIRS for part in p.parts)


def detect_languages(project_dir: Path) -> List[str]:
    """Detects languages present in the project using LanguageRegistry manifests and extensions."""
    languages: List[str] = []
    include_dirs = load_include_dirs(project_dir)

    def _is_path_included(p: Path) -> bool:
        return include_dirs is None or is_included(str(p.relative_to(project_dir)), include_dirs)

    for spec in LanguageRegistry.get_all_specs():
        if not spec.scip_binary or spec.name == "javascript":
            continue
        lang = spec.name

        detected = any((project_dir / manifest).exists() for manifest in spec.manifest_names)

        if not detected and spec.manifest_names:
            for manifest in spec.manifest_names:
                for p in project_dir.rglob(manifest):
                    if _has_excluded_part(p):
                        continue
                    if _is_path_included(p):
                        detected = True
                        break
                if detected:
                    break

        if not detected and spec.extensions:
            for ext in spec.extensions:
                for p in project_dir.glob(f"**/*{ext}"):
                    if _has_excluded_part(p):
                        continue
                    if _is_path_included(p):
                        detected = True
                        break
                if detected:
                    break

        if detected and lang not in languages:
            languages.append(lang)

    return languages


def verify_environment(languages: List[str]) -> Dict[str, bool]:
    """Checks if the required toolchains are installed and available."""
    status: Dict[str, bool] = {}
    for lang in languages:
        spec = LanguageRegistry.get_spec(lang)
        if not spec:
            status[lang] = False
            continue
        bin_found = bool(spec.scip_binary and shutil.which(spec.scip_binary) is not None)
        if not bin_found and spec.tool_names:
            bin_found = any(shutil.which(tool) is not None for tool in spec.tool_names)
        status[lang] = bin_found
    return status


__all__ = [
    "detect_languages",
    "verify_environment",
    "run_indexer",
    "parse_index",
    "ingest_index",
    "_move_index_to_arch",
]
