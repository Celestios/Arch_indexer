import os
import sys
from pathlib import Path
from contextlib import contextmanager

from db.connection import DbConnection
from db.repository import Repository
from utils.helpers import CONFIG_DIR_NAME
from utils.helpers import resolve_filepath  # noqa: F401 - re-export for backward compatibility


def get_project_root(args=None) -> Path:
    """Get the project root from args, environment variable, sys.argv, or CWD."""
    env_root = os.environ.get("ARCH_PROJECT_ROOT")
    if env_root:
        if args is None or not hasattr(args, "project_root") or args.project_root == ".":
            return Path(env_root).resolve()

    if args is not None and hasattr(args, "project_root"):
        return Path(args.project_root).resolve()

    for arg in sys.argv[2:]:
        if not arg.startswith("-"):
            return Path(arg).resolve()

    return Path.cwd().resolve()


@contextmanager
def workspace_session(args):
    """Context manager that validates workspace, creates Repository, and handles cleanup."""
    project_root = get_project_root(args)
    arch_dir = project_root / CONFIG_DIR_NAME
    if not arch_dir.exists():
        print("Error: Workspace not initialized. Run 'arch init' first.", file=sys.stderr)
        sys.exit(1)
    db_conn = DbConnection(arch_dir / "arch.db")
    repository = Repository(db_conn)
    try:
        from utils.single_instance import register_workspace
        register_workspace(project_root)
    except Exception:
        pass
    try:
        yield project_root, arch_dir, repository
    finally:
        db_conn.close()


@contextmanager
def db_session(project_root: Path):
    """Context manager that yields (repository, db_conn) for a given project root."""
    from utils.helpers import CONFIG_FILE_NAME
    arch_dir = project_root / CONFIG_DIR_NAME
    db_path = arch_dir / "arch.db"
    if not db_path.exists():
        raise FileNotFoundError(
            f"Arch database not found at {db_path}. Please run 'arch init' first."
        )
    db_conn = DbConnection(db_path)
    repository = Repository(db_conn)
    try:
        yield repository, db_conn
    finally:
        db_conn.close()
