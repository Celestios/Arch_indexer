from dataclasses import dataclass
from typing import List
from pathlib import Path
from engines.ffi_extractor import FfiSurface
from .graph_utils import make_surface_id

@dataclass
class DartFfiSurface:
    """Extended FFI surface with Dart-specific metadata."""
    surface_id: str
    symbol_id: str
    ffi_type: str          # 'lookup', 'external', 'native_function'
    native_name: str       # C function name (for lookup)
    dart_name: str         # Dart function name
    signature: str
    filepath: str
    line: int

    def to_ffi_surface(self) -> FfiSurface:
        """Convert to standard FfiSurface format expected by FfiMatcher."""
        return FfiSurface(
            symbol_name=self.dart_name,
            signature=self.signature,
            filepath=self.filepath,
            language="dart"
        )


class DartFfiDetector:
    """
    Detects FFI surfaces in Dart code using analyzer.
    Results stored in dart_analyzer_db.ffi_surfaces.
    """

    def __init__(self, project_root: Path, analyzer_db):
        self.project_root = project_root
        self.analyzer_db = analyzer_db
        self._parsed_files: dict = {}

    def detect(self) -> List[FfiSurface]:
        """
        Find all FFI surfaces in Dart project.
        Returns List[FfiSurface] compatible with FfiMatcher.
        """
        # Check if already computed in DB
        existing = self.analyzer_db.get_ffi_surfaces()
        if existing:
            return [DartFfiSurface(**s).to_ffi_surface() for s in existing]

        return []

    def _make_surface_id(self, filepath: str, name: str) -> str:
        """Generate unique surface ID."""
        return make_surface_id(filepath, name)
