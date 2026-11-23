import importlib

from commands.init import cmd_init
from commands.audit import cmd_audit
from commands.history import cmd_history
from commands.watch import cmd_watch
from commands.analyze import cmd_analyze
from commands.impact import cmd_impact
from commands.set_status import cmd_set_status
from commands.set_fields import cmd_set_fields
from commands.clear_pending import cmd_clear_pending
from commands.clusters import cmd_clusters
from commands.graph import cmd_graph
from commands.mcp import cmd_mcp

# Explicit list of CLI command modules. Order = order shown in --help.
COMMANDS = [
    "analyze",
    "audit",
    "clear_pending",
    "clusters",
    "graph",
    "history",
    "impact",
    "init",
    "mcp",
    "set_fields",
    "set_status",
    "watch",
]


def register_all(subparsers) -> None:
    """Register every CLI subcommand listed in COMMANDS."""
    for module_name in COMMANDS:
        mod = importlib.import_module(f"commands.{module_name}")
        mod.register(subparsers)


__all__ = [
    "COMMANDS",
    "register_all",
    "cmd_init",
    "cmd_audit",
    "cmd_clusters",
    "cmd_history",
    "cmd_watch",
    "cmd_analyze",
    "cmd_impact",
    "cmd_set_status",
    "cmd_set_fields",
    "cmd_clear_pending",
    "cmd_mcp",
]
