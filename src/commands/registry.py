import pkgutil
import importlib
import sys
from pathlib import Path

EXCLUDE = {"__init__.py", "main.py", "registry.py", "__pycache__"}


def register_all(subparsers) -> None:
    commands_dir = Path(__file__).parent
    for _, module_name, _ in pkgutil.iter_modules([str(commands_dir)]):
        if module_name in EXCLUDE:
            continue
        mod = importlib.import_module(f"commands.{module_name}")
        if hasattr(mod, "register"):
            mod.register(subparsers)
