"""
Code Extractor Re-export for Graph Builder.
Imports CodeExtractor from the core arch index utils.
"""

try:
    from utils.code_extractor import CodeExtractor
except ImportError:
    from src.utils.code_extractor import CodeExtractor

__all__ = ["CodeExtractor"]
