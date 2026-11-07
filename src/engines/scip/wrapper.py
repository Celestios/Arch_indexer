import shutil
from pathlib import Path
from typing import Dict, List, Any, Optional

from utils.exclusions import load_include_dirs, is_included
from engines.scip.indexers import (
    index_rust, index_dart, index_python, index_generic, _move_index_to_arch
)
from engines.scip.parser import ScipParser
from engines.scip.ingester import IndexIngester
from engines.edge_weights import EdgeWeightCalculator


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
    def parse_index(scip_file: Path, project_root: Optional[Path] = None) -> Dict[str, Any]:
        """
        Parses a binary index.scip file into a normalized dictionary
        of symbols, occurrences, and edges.
        Filters by include_dirs from config.json if project_root is provided.
        """
        return ScipParser.parse_index(scip_file, project_root)

    @staticmethod
    def _get_symbol_layer(filepath: str, config: Dict[str, Any]) -> str:
        if not filepath:
            return ""
        norm_path = filepath.replace("\\", "/")
        best_prefix = ""
        best_conf = None
        for prefix, prefix_conf in config.items():
            if norm_path.startswith(prefix) and len(prefix) > len(best_prefix):
                best_prefix = prefix
                best_conf = prefix_conf
        if not best_conf:
            return ""

        layer_conf = best_conf.get("automatic_fields", {}).get("layer", {})
        if not layer_conf:
            return ""

        assigned_val = layer_conf.get("default", "")
        rules = layer_conf.get("assignment_rules", [])
        for rule in rules:
            conds = rule.get("conditions", {})
            val = rule.get("value")
            if conds.get("path_prefix") and norm_path.startswith(conds["path_prefix"]):
                assigned_val = val
                break
        return assigned_val

    @staticmethod
    def calculate_edge_weight(source_filepath: str, target_filepath: str, config: Dict[str, Any]) -> float:
        if not source_filepath or not target_filepath:
            return 1.0

        src_layer = ScipWrapper._get_symbol_layer(source_filepath, config)
        tgt_layer = ScipWrapper._get_symbol_layer(target_filepath, config)

        src_fields = {"layer": src_layer} if src_layer else None
        tgt_fields = {"layer": tgt_layer} if tgt_layer else None
        all_barriers = EdgeWeightCalculator.collect_barriers(config)
        weight = EdgeWeightCalculator.calculate_weight(src_fields, tgt_fields, all_barriers)

        if src_layer and tgt_layer and src_layer != tgt_layer:
            for prefix_conf in config.values():
                rules = prefix_conf.get("automatic_fields", {}).get("layer", {}).get("rules", [])
                for rule in rules:
                    if rule.get("source") == src_layer and rule.get("target") == tgt_layer:
                        weight *= 0.5
                        break
        return weight

    @staticmethod
    def ingest_index(repository, parsed_data, project_root=None, force=False, config=None):
        """
        Ingests the parsed symbols, occurrences, and edges into the database.
        Uses incremental ingestion: only processes files whose content has changed.
        """
        return IndexIngester.ingest_index(
            repository, parsed_data, project_root, force, config
        )
