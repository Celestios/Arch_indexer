import json
import os
from pathlib import Path
from typing import List, Optional


REGISTRY_DIR = Path(os.environ.get("APPDATA", Path.home() / ".config")) / "arch-mcp"
REGISTRY_FILE = REGISTRY_DIR / "projects.json"


def _ensure_registry_dir():
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)


def _load_registry() -> dict:
    if REGISTRY_FILE.exists():
        with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"projects": []}


def _save_registry(data: dict):
    _ensure_registry_dir()
    with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def register_project(project_root: Path):
    """Register a project when 'arch init' runs."""
    project_root = project_root.resolve()
    registry = _load_registry()

    entry = {
        "path": str(project_root),
        "arch_dir": str(project_root / ".arch"),
        "db_path": str(project_root / ".arch" / "arch.db")
    }

    # Update if exists, otherwise add
    existing = [p for p in registry["projects"] if p["path"] == str(project_root)]
    if existing:
        existing[0].update(entry)
    else:
        registry["projects"].append(entry)

    _save_registry(registry)
    print(f"[Registry] Project registered: {project_root}")


def find_project_root() -> Optional[Path]:
    """
    Find a project root by searching:
    1. Registered projects (most recent first)
    2. CWD and parents for .arch/ directory
    """
    # 1. Check registered projects
    registry = _load_registry()
    if registry.get("projects"):
        # Return the most recently registered project
        for proj in reversed(registry["projects"]):
            db_path = Path(proj["db_path"])
            if db_path.exists():
                return Path(proj["path"])

    # 2. Search upward from CWD
    current = Path.cwd()
    for parent in [current] + list(current.parents):
        if (parent / ".arch" / "arch.db").exists():
            return parent

    return None


def get_db_path(project_root: Optional[Path] = None) -> Optional[Path]:
    """Get the database path for a project."""
    if project_root is None:
        project_root = find_project_root()
    if project_root:
        db_path = project_root / ".arch" / "arch.db"
        if db_path.exists():
            return db_path
    return None


def list_projects() -> List[dict]:
    """List all registered projects."""
    registry = _load_registry()
    return registry.get("projects", [])


def unregister_project(project_root: Path):
    """Remove a project from the registry."""
    project_root = project_root.resolve()
    registry = _load_registry()
    registry["projects"] = [p for p in registry["projects"] if p["path"] != str(project_root)]
    _save_registry(registry)
