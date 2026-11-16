#!/usr/bin/env python3
"""
Executable entry point for the Arch PCB Circuit Board HTML Graph Builder.
Directly reads the DuckDB database and generates a zoom-able electronic motherboard schematic.
"""

import sys
import os

# Add root directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from graph_builder.cli import main

if __name__ == "__main__":
    main()
