"""
Backwards-compatibility shim.

All logic has moved to engines.scip.* submodules.
This module re-exports the public API so existing imports continue to work:
    from engines.scip_wrapper import ScipWrapper
"""
from engines.scip.wrapper import ScipWrapper
from engines.scip.parser import ScipParser
from engines.scip.ingester import IndexIngester
from engines.scip.utils import print_progress, run_with_scroll

__all__ = ["ScipWrapper", "ScipParser", "IndexIngester", "print_progress", "run_with_scroll"]
