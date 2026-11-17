#!/usr/bin/env python3
"""
Script to extract and update graph_builder files from transmit (3).txt.
"""
import ast
import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
TRANSMIT_FILE = BASE_DIR / "transmit (3).txt"

FILES_SPEC = [
    ("src/graph_builder/circuit_config.json", 24, 72, "json"),
    ("circuit_config.json", 24, 72, "json"),
    ("src/graph_builder/config.py", 75, 179, "py"),
    ("src/graph_builder/layout/zone_classifier.py", 182, 388, "py"),
    ("src/graph_builder/layout/package_sizer.py", 391, 620, "py"),
    ("src/graph_builder/layout/circuit_layout.py", 623, 976, "py"),
    ("src/graph_builder/routing/channel_router.py", 979, 1360, "py"),
    ("src/graph_builder/serialization/compressor.py", 1363, 1507, "py"),
    ("src/graph_builder/renderer/canvas_engine.py", 1511, 2462, "py"),
    ("src/graph_builder/cli.py", 2466, 2592, "py"),
    ("src/graph_builder/__init__.py", 2595, 2637, "py"),
]


def update_files():
    if not TRANSMIT_FILE.exists():
        raise FileNotFoundError(f"Source file not found: {TRANSMIT_FILE}")

    with open(TRANSMIT_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()

    for rel_path, start, end, ftype in FILES_SPEC:
        content = "".join(lines[start - 1 : end])
        dest_path = BASE_DIR / rel_path
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        if ftype == "json":
            json.loads(content)  # Validate JSON syntax
        elif ftype == "py":
            ast.parse(content)  # Validate Python AST syntax

        with open(dest_path, "w", encoding="utf-8", newline="\n") as out_f:
            out_f.write(content)

        print(f"[+] Updated: {rel_path} ({len(content)} bytes)")


if __name__ == "__main__":
    update_files()
