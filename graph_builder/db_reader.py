"""
Backwards-compatible facade re-exporting DatabaseReader and ScipParser.
"""

from .ingestion.db_reader import DatabaseReader
from .ingestion.scip_parser import ScipParser

__all__ = ["DatabaseReader", "ScipParser"]
