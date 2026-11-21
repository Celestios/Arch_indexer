import sys
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from utils.exclusions import load_include_dirs, is_included
from utils.helpers import IS_WINDOWS
from engines.registry import LanguageRegistry
from engines.scip.utils import run_with_scroll


def _find_arch_dir(start_dir: Path) -> Path:
    """Find the nearest .arch directory traversing upwards."""
    curr = start_dir.resolve()
    while True:
        candidate = curr / ".arch"
        if candidate.is_dir():
            return candidate
        if curr.parent == curr:
            break
        curr = curr.parent
    return start_dir / ".arch"


def _move_index_to_arch(project_dir: Path, language: str, cargo_root: Path = None) -> Optional[Path]:
    """Move generated index.scip to .arch/index_{language}.scip."""
    arch_dir = _find_arch_dir(project_dir)
    arch_index = arch_dir / f"index_{language}.scip"
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
        if include_dirs is not None:
            rel = str(p.relative_to(project_dir))
            cargo_dir_rel = str(p.parent.relative_to(project_dir)).replace("\\", "/")
            is_parent = any(
                str(Path(inc)).replace("\\", "/").startswith(cargo_dir_rel + "/")
                for inc in include_dirs
            )
            if not is_included(rel, include_dirs) and not is_parent:
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

    # Check if scip_dart is already activated globally
    is_activated = False
    try:
        res = subprocess.run(
            ["dart", "pub", "global", "list"],
            cwd=str(pubspec_dir),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, shell=IS_WINDOWS
        )
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                parts = line.strip().split()
                if parts and parts[0] == "scip_dart":
                    is_activated = True
                    break
    except Exception:
        pass

    if not is_activated:
        try:
            res = subprocess.run(
                ["dart", "pub", "global", "activate", "scip_dart"],
                cwd=str(pubspec_dir),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, shell=IS_WINDOWS
            )
            if res.returncode != 0:
                print(f"Warning: Failed to activate scip_dart. Output:\n{res.stderr or res.stdout}", file=sys.stderr)
        except Exception as e:
            print(f"Warning: Failed to run dart pub global activate scip_dart: {e}", file=sys.stderr)

    try:
        rc = run_with_scroll(
            ["dart", "pub", "global", "run", "scip_dart", "."],
            cwd=str(pubspec_dir), shell=IS_WINDOWS
        )
        if rc != 0:
            raise subprocess.CalledProcessError(rc, "scip_dart")
        return _move_index_to_arch(project_dir, "dart", pubspec_dir)
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
    """Indexer for languages driven by LanguageSpec in LanguageRegistry."""
    spec = LanguageRegistry.get_spec(language)
    if spec and spec.scip_command:
        cmd = list(spec.scip_command)
    else:
        tool_name = spec.scip_binary if spec and spec.scip_binary else f"scip-{language}"
        cmd = [tool_name]
    tool_name = cmd[0]
    print(f"[SCIP] Indexing {language.capitalize()} project under {project_dir}...")
    if not shutil.which(tool_name):
        print(f"Error: {tool_name} CLI is not on the system PATH.", file=sys.stderr)
        return None
    try:
        rc = run_with_scroll(cmd, cwd=str(project_dir), shell=IS_WINDOWS)
        if rc != 0:
            raise subprocess.CalledProcessError(rc, tool_name)
        return _move_index_to_arch(project_dir, language)
    except subprocess.CalledProcessError as e:
        print(f"Error executing {tool_name}: {e}", file=sys.stderr)
        return None


_INDEXERS = {
    "dart": index_dart,
    "rust": index_rust,
    "python": index_python,
}


def run_indexer(project_dir: Path, language: str) -> Optional[Path]:
    """Executes the appropriate indexer for a language."""
    indexer = _INDEXERS.get(language)
    if indexer:
        return indexer(project_dir)
    return index_generic(project_dir, language)
