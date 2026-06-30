from dataclasses import dataclass
from typing import List
from pathlib import Path
import hashlib
from engines.ffi_extractor import FfiSurface

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

        # Run detection
        from .visitors.ffi_visitor import FfiVisitor

        surfaces = []
        visitor = FfiVisitor()

        for filepath, unit in self._parsed_files.items():
            unit.visit(visitor)
            for result in visitor.results:
                dart_surface = DartFfiSurface(
                    surface_id=self._make_surface_id(filepath, result['name']),
                    symbol_id=result['symbol_id'],
                    ffi_type=result['type'],
                    native_name=result.get('native_name', ''),
                    dart_name=result['name'],
                    signature=result['signature'],
                    filepath=str(filepath),
                    line=result['line']
                )
                surfaces.append(dart_surface)

                # Store in analyzer DB
                self.analyzer_db.upsert_ffi_surface(
                    surface_id=dart_surface.surface_id,
                    symbol_id=dart_surface.symbol_id,
                    ffi_type=dart_surface.ffi_type,
                    native_name=dart_surface.native_name,
                    dart_name=dart_surface.dart_name,
                    signature=dart_surface.signature,
                    filepath=dart_surface.filepath,
                    line=dart_surface.line
                )
            visitor.results.clear()

        # Convert to standard FfiSurface format
        return [s.to_ffi_surface() for s in surfaces]

    def _make_surface_id(self, filepath: str, name: str) -> str:
        """Generate unique surface ID."""
        raw = f"{filepath}::{name}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
