import sys
from pathlib import Path
from contextlib import contextmanager

from db.connection import DbConnection
from db.repository import Repository


def get_project_root(args) -> Path:
    """Get the project root from args or environment variable."""
    import os
    env_root = os.environ.get("ARCH_PROJECT_ROOT")
    if env_root and (not hasattr(args, "project_root") or args.project_root == "."):
        return Path(env_root).resolve()
    return Path(args.project_root).resolve()


@contextmanager
def workspace_session(args):
    """Context manager that validates workspace, creates Repository, and handles cleanup."""
    project_root = get_project_root(args)
    arch_dir = project_root / ".arch"
    if not arch_dir.exists():
        print("Error: Workspace not initialized. Run 'arch init' first.", file=sys.stderr)
        sys.exit(1)
    db_conn = DbConnection(arch_dir / "arch.db")
    repository = Repository(db_conn)
    try:
        yield project_root, arch_dir, repository
    finally:
        db_conn.close()


def resolve_filepath(repository, raw_path: str) -> str:
    """Resolve a filepath against the database, trying exact match then suffix fallback."""
    from utils.helpers import resolve_filepath as _resolve_filepath
    return _resolve_filepath(repository, raw_path)
