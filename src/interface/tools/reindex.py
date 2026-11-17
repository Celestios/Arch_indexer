"""Backward-compatibility module; see interface.tools.update."""
from interface.tools.update import handle_update, handle_update as handle_reindex

__all__ = ["handle_update", "handle_reindex"]
