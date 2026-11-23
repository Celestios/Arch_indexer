import time
from pathlib import Path
from typing import Set

from engines.registry import LanguageRegistry

_WATCHED_EXTENSIONS = LanguageRegistry.list_extensions()


def _resolve_package_root(file_path: Path, project_root: Path, lang: str) -> Path:
    """Find the nearest directory containing Cargo.toml or pubspec.yaml (or other package manifests)."""
    manifest_name = LanguageRegistry.get_manifest_for_language(lang)
    if not manifest_name:
        return project_root

    curr = file_path.resolve()
    if curr.is_file():
        curr = curr.parent

    proj_resolved = project_root.resolve()
    while True:
        if (curr / manifest_name).exists():
            return curr
        if curr == proj_resolved or curr.parent == curr:
            break
        curr = curr.parent

    return project_root


_FFI_BRIDGE_INDICATORS = ("bridge", "ffi")


def _has_ffi_bridge_files(files) -> bool:
    """Check if any file in the batch belongs to an FFI bridge directory or filename pattern."""
    for f in files:
        f_str = str(f).replace("\\", "/").lower()
        if any(indicator in f_str for indicator in _FFI_BRIDGE_INDICATORS):
            return True
    return False


def start_watcher(project_root: Path, debounce: float = 3.0):
    from change_tracker.watcher_manager import ProjectWatcher
    watcher = ProjectWatcher(project_root, debounce=debounce)
    if not watcher.start():
        return
    print(f"[arch watch] Watching {project_root} for changes... (Press Ctrl+C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[arch watch] Stopped.")
    finally:
        watcher.stop()

