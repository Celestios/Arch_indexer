import shutil
from pathlib import Path
from typing import Dict, List, Any, Optional

from utils.exclusions import load_include_dirs, is_included
from engines.registry import LanguageRegistry
from engines.scip.indexers import run_indexer, _move_index_to_arch
from engines.scip.parser import ScipParser
from engines.scip.ingester import IndexIngester


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


def verify_environment(languages: List[str]) -> Dict[str, bool]:
    """Checks if the required toolchains are installed and available."""
    status: Dict[str, bool] = {}
    for lang in languages:
        spec = LanguageRegistry.get_spec(lang)
        if not spec:
            status[lang] = False
            continue
        bin_found = False
        if spec.scip_binary:
            bin_found = shutil.which(spec.scip_binary) is not None
        if not bin_found and spec.tool_names:
            bin_found = any(shutil.which(tool) is not None for tool in spec.tool_names)
        status[lang] = bin_found
    return status


def parse_index(
    scip_file: Path,
    project_root: Optional[Path] = None,
    changed_files: Optional[Any] = None
) -> Dict[str, Any]:
    """Parses binary index.scip file into normalized dict of symbols, occurrences, and edges."""
    return ScipParser.parse_index(scip_file, project_root, changed_files=changed_files)


def ingest_index(repository, parsed_data, project_root=None, force=False, config=None):
    """Ingests parsed symbols, occurrences, and edges into the database."""
    return IndexIngester.ingest_index(repository, parsed_data, project_root, force)
