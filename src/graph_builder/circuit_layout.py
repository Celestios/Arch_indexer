"""
Backwards-compatible facade re-exporting CircuitLayoutEngine and compress_circuit_data.
"""

from .layout.circuit_layout import CircuitLayoutEngine
from .serialization.compressor import compress_circuit_data

__all__ = ["CircuitLayoutEngine", "compress_circuit_data"]
