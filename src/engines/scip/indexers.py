import sys
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from utils.exclusions import load_include_dirs, is_included
from utils.helpers import IS_WINDOWS
from engines.scip.utils import run_with_scroll


def _move_index_to_arch(project_dir: Path, language: str, cargo_root: Path = None) -> Optional[Path]:
    """Move generated index.scip to .arch/index_{language}.scip."""
    arch_index = project_dir / ".arch" / f"index_{language}.scip"
    search_dirs = [project_dir]
    if cargo_root and cargo_root != project_dir:
        search_dirs.append(cargo_root)
    for d in search_dirs:
        index_path = d / "index.scip"
        if index_path.exists():
            arch_index.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(index_path), str(arch_index))
            return arch_index
    if arch_index.exists():
        return arch_index
    return None


def _find_cargo_root(project_dir: Path) -> Path:
    """Find the directory containing Cargo.toml, preferring root, then subdirectories."""
    if (project_dir / "Cargo.toml").exists():
        return project_dir
    include_dirs = load_include_dirs(project_dir)
    for p in project_dir.rglob("Cargo.toml"):
        if "target" in str(p) or ".arch" in str(p):
            continue
        if include_dirs is not None and not is_included(str(p.relative_to(project_dir)), include_dirs):
            continue
        return p.parent
    return project_dir


def index_rust(project_dir: Path) -> Optional[Path]:
    cargo_root = _find_cargo_root(project_dir)
    print(f"[SCIP] Indexing Rust project under {cargo_root}...")
    ra_cmd = ["rust-analyzer", "scip", "."]
    if shutil.which("rustup"):
        ra_cmd = ["rustup", "run", "stable", "rust-analyzer", "scip", "."]

    try:
        rc = run_with_scroll(ra_cmd, cwd=str(cargo_root), shell=IS_WINDOWS)
        if rc != 0:
            raise subprocess.CalledProcessError(rc, "rust-analyzer")
        return _move_index_to_arch(project_dir, "rust", cargo_root)
    except subprocess.CalledProcessError:
        print("Warning: rust-analyzer CLI was not found. Attempting to add it via rustup...")
        try:
            subprocess.run(["rustup", "component", "add", "rust-analyzer"], check=True, shell=IS_WINDOWS)
            rc = run_with_scroll(["rust-analyzer", "scip", "."], cwd=str(cargo_root), shell=IS_WINDOWS)
            if rc != 0:
                raise subprocess.CalledProcessError(rc, "rust-analyzer")
            return _move_index_to_arch(project_dir, "rust", cargo_root)
        except Exception as err:
            print(f"Error: Failed to execute rust-analyzer scip: {err}", file=sys.stderr)
            print("Notice: If you are using the rust-analyzer extension inside VS Code, the CLI component must still be installed globally.", file=sys.stderr)
            print("To enable Rust indexing on the command-line, run:\n    rustup component add rust-analyzer", file=sys.stderr)
            return None


def index_dart(project_dir: Path) -> Optional[Path]:
    print(f"[SCIP] Indexing Dart project under {project_dir}...")
    if not shutil.which("dart"):
        print("Error: Dart SDK is not on the system PATH.", file=sys.stderr)
        return None

    pubspec_dir = project_dir
    if not (project_dir / "pubspec.yaml").exists():
        pubspecs = [p for p in project_dir.rglob("pubspec.yaml")
                    if ".dart_tool" not in str(p) and "dart_analyzer" not in str(p)]
        if not pubspecs:
            print("[SCIP] No pubspec.yaml found, skipping Dart indexing.")
            return None
        pubspec_dir = pubspecs[0].parent
        print(f"[SCIP] Using pubspec at {pubspec_dir}")

    try:
        subprocess.run(
            ["dart", "pub", "global", "activate", "scip_dart"],
            cwd=str(pubspec_dir), check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            shell=IS_WINDOWS
        )
    except subprocess.CalledProcessError as e:
        print(f"Warning: Failed to activate scip_dart: {e}", file=sys.stderr)

    try:
        rc = run_with_scroll(
            ["dart", "pub", "global", "run", "scip_dart", "."],
            cwd=str(pubspec_dir), shell=IS_WINDOWS
        )
        if rc != 0:
            raise subprocess.CalledProcessError(rc, "scip_dart")
        return _move_index_to_arch(project_dir, "dart")
    except subprocess.CalledProcessError as e:
        print(f"Error executing scip_dart indexer: {e}", file=sys.stderr)
        return None


def index_python(project_dir: Path) -> Optional[Path]:
    print(f"[SCIP] Indexing Python project under {project_dir}...")
    if not shutil.which("scip-python"):
        print("Error: scip-python CLI is not on the system PATH.", file=sys.stderr)
        return None
    try:
        arch_index = project_dir / ".arch" / f"index_python.scip"
        arch_index.parent.mkdir(parents=True, exist_ok=True)
        rc = run_with_scroll(
            ["scip-python", "index", "--project-name", str(project_dir.name),
             "--output", str(arch_index)],
            cwd=str(project_dir), shell=IS_WINDOWS
        )
        if rc != 0:
            raise subprocess.CalledProcessError(rc, "scip-python")
        if arch_index.exists():
            return arch_index
    except subprocess.CalledProcessError as e:
        print(f"Error executing scip-python: {e}", file=sys.stderr)
        return None


def index_generic(project_dir: Path, language: str) -> Optional[Path]:
    """Indexer for languages with simple `tool [subcommand]` invocations."""
    tool_map = {
        "go": ("scip-go", []),
        "typescript": ("scip-typescript", ["index"]),
        "java": ("scip-java", ["index"]),
    }
    tool_name, extra_args = tool_map.get(language, (f"scip-{language}", []))
    print(f"[SCIP] Indexing {language.capitalize()} project under {project_dir}...")
    if not shutil.which(tool_name):
        print(f"Error: {tool_name} CLI is not on the system PATH.", file=sys.stderr)
        return None
    try:
        rc = run_with_scroll([tool_name] + extra_args, cwd=str(project_dir), shell=IS_WINDOWS)
        if rc != 0:
            raise subprocess.CalledProcessError(rc, tool_name)
        return _move_index_to_arch(project_dir, language)
    except subprocess.CalledProcessError as e:
        print(f"Error executing {tool_name}: {e}", file=sys.stderr)
        return None
