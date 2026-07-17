import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add src to path
import sys
src_dir = Path(__file__).resolve().parent.parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from engines.dart_analyzer import (
    DartAnalyzerWrapper,
    DartAnalyzerDB,
    DartDataflowTracer,
    FlowStep,
    DartFfiDetector,
    DartFfiSurface,
)
from engines.ffi_extractor import FfiSurface
from engines.ffi_matcher import FfiMatcher, FfiMatch


class TestDartAnalyzerDB:
    """Tests for the DartAnalyzerDB database layer."""

    def test_initialize_creates_database(self, tmp_path):
        """Database initialization creates the directory and schema."""
        arch_dir = tmp_path / ".arch"
        db = DartAnalyzerDB(arch_dir)
        db.initialize()
        assert db.db_dir.exists()
        assert db.db_path.exists()
        assert db.is_available()

    def test_upsert_parsed_file(self, tmp_path):
        """Can insert and update parsed file records."""
        arch_dir = tmp_path / ".arch"
        db = DartAnalyzerDB(arch_dir)
        db.initialize()
        db.upsert_parsed_file("lib/main.dart", "abc123")
        db.upsert_parsed_file("lib/utils.dart", "def456")
        with db.session() as conn:
            rows = conn.execute("SELECT * FROM parsed_files").fetchall()
            assert len(rows) == 2

    def test_upsert_resolved_symbol(self, tmp_path):
        """Can insert type-resolved symbols."""
        arch_dir = tmp_path / ".arch"
        db = DartAnalyzerDB(arch_dir)
        db.initialize()
        db.upsert_resolved_symbol(
            symbol_id="my_lib::MyClass",
            filepath="lib/my_class.dart",
            kind="Class",
            type_name="MyClass",
            return_type=None,
            parameters=None,
            is_nullable=False,
            line=10,
            col=0
        )
        symbol = db.get_resolved_symbol("my_lib::MyClass")
        assert symbol is not None
        assert symbol["kind"] == "Class"
        assert symbol["line"] == 10

    def test_upsert_ffi_surface(self, tmp_path):
        """Can insert FFI surfaces."""
        arch_dir = tmp_path / ".arch"
        db = DartAnalyzerDB(arch_dir)
        db.initialize()
        db.upsert_ffi_surface(
            surface_id="surface_123",
            symbol_id="my_lib::native_func",
            ffi_type="lookup",
            native_name="native_function",
            dart_name="lookup_native",
            signature="void Function(int)",
            filepath="lib/ffi.dart",
            line=25
        )
        surfaces = db.get_ffi_surfaces()
        assert len(surfaces) == 1
        assert surfaces[0]["ffi_type"] == "lookup"
        assert surfaces[0]["native_name"] == "native_function"

    def test_cache_and_get_dataflow_path(self, tmp_path):
        """Can cache and retrieve dataflow paths."""
        arch_dir = tmp_path / ".arch"
        db = DartAnalyzerDB(arch_dir)
        db.initialize()
        path = ["source_func", "intermediate", "sink_func"]
        db.cache_dataflow_path("source_func", "sink_func", path, 3)
        cached = db.get_dataflow_path("source_func", "sink_func")
        assert cached == path

    def test_get_dataflow_path_returns_none_when_missing(self, tmp_path):
        """Returns None for non-existent dataflow path."""
        arch_dir = tmp_path / ".arch"
        db = DartAnalyzerDB(arch_dir)
        db.initialize()
        cached = db.get_dataflow_path("missing_source", "missing_sink")
        assert cached is None


class TestDartAnalyzerWrapper:
    """Tests for the DartAnalyzerWrapper API compatibility."""

    def test_is_available_returns_true_natively(self, tmp_path):
        """Returns True since it is now natively supported in pure-Python."""
        wrapper = DartAnalyzerWrapper(tmp_path)
        assert wrapper.is_available() is True

    def test_create_database_returns_false_for_non_dart(self, tmp_path):
        """Returns False when language is not dart."""
        wrapper = DartAnalyzerWrapper(tmp_path)
        result = wrapper.create_database(tmp_path, tmp_path / "db", "rust")
        assert result is False

    def test_create_database_succeeds_natively(self, tmp_path):
        """Returns True when database is created successfully."""
        wrapper = DartAnalyzerWrapper(tmp_path)
        result = wrapper.create_database(tmp_path, tmp_path / "db", "dart")
        assert result is True

    def test_trace_data_flow_returns_correct_format(self, tmp_path):
        """trace_data_flow returns dict format expected by server.py."""
        arch_dir = tmp_path / ".arch"
        db = DartAnalyzerDB(arch_dir)
        db.initialize()

        # Add symbols
        db.upsert_resolved_symbol(
            symbol_id="source_func",
            filepath="lib/main.dart",
            kind="Function",
            type_name="void",
            return_type="void",
            parameters="()",
            is_nullable=False,
            line=10,
            col=0
        )
        db.upsert_resolved_symbol(
            symbol_id="sink_func",
            filepath="lib/utils.dart",
            kind="Function",
            type_name="void",
            return_type="void",
            parameters="()",
            is_nullable=False,
            line=20,
            col=0
        )
        db.cache_dataflow_path("source_func", "sink_func",
                              ["source_func", "sink_func"], 2)

        wrapper = DartAnalyzerWrapper(arch_dir)
        steps = wrapper.trace_data_flow(
            db_dir=arch_dir / "nonexistent",
            source_symbol="source_func",
            sink_symbol="sink_func"
        )

        # Verify format matches what server.py expects
        assert len(steps) == 2
        for step in steps:
            assert "symbol" in step
            assert "filepath" in step
            assert "line" in step
            assert isinstance(step["symbol"], str)
            assert isinstance(step["filepath"], str)
            assert isinstance(step["line"], int)

    def test_detect_ffi_returns_ffi_surface_list(self, tmp_path):
        """detect_ffi returns List[FfiSurface] compatible with FfiMatcher."""
        arch_dir = tmp_path / ".arch"
        db = DartAnalyzerDB(arch_dir)
        db.initialize()

        # Add FFI surface to DB
        db.upsert_ffi_surface(
            surface_id="surface_123",
            symbol_id="my_lib::native_func",
            ffi_type="lookup",
            native_name="native_function",
            dart_name="lookup_native",
            signature="void Function(int)",
            filepath="lib/ffi.dart",
            line=25
        )

        wrapper = DartAnalyzerWrapper(arch_dir)
        # Mock _parsed_files since analyzer not available
        wrapper._parsed_files = {}

        surfaces = wrapper.detect_ffi()

        # Verify format matches FfiSurface dataclass
        assert len(surfaces) == 1
        assert isinstance(surfaces[0], FfiSurface)
        assert surfaces[0].symbol_name == "lookup_native"
        assert surfaces[0].signature == "void Function(int)"
        assert surfaces[0].filepath == "lib/ffi.dart"
        assert surfaces[0].language == "dart"


class TestFlowStep:
    """Tests for the FlowStep dataclass."""

    def test_flow_step_creation(self):
        """FlowStep can be created with required fields."""
        step = FlowStep(
            symbol="my_func",
            filepath="lib/main.dart",
            line=42,
            col=10
        )
        assert step.symbol == "my_func"
        assert step.filepath == "lib/main.dart"
        assert step.line == 42
        assert step.col == 10
        assert step.type_name is None

    def test_flow_step_with_type(self):
        """FlowStep can be created with optional type_name."""
        step = FlowStep(
            symbol="my_func",
            filepath="lib/main.dart",
            line=42,
            col=10,
            type_name="void Function(int)"
        )
        assert step.type_name == "void Function(int)"


class TestDartFfiSurface:
    """Tests for the DartFfiSurface dataclass."""

    def test_ffi_surface_creation(self):
        """DartFfiSurface can be created with all fields."""
        surface = DartFfiSurface(
            surface_id="abc123",
            symbol_id="my_lib::native_func",
            ffi_type="lookup",
            native_name="native_function",
            dart_name="lookup_native",
            signature="void Function(int)",
            filepath="lib/ffi.dart",
            line=25
        )
        assert surface.ffi_type == "lookup"
        assert surface.native_name == "native_function"

    def test_to_ffi_surface_conversion(self):
        """DartFfiSurface.to_ffi_surface() returns FfiSurface."""
        dart_surface = DartFfiSurface(
            surface_id="abc123",
            symbol_id="my_lib::native_func",
            ffi_type="lookup",
            native_name="native_function",
            dart_name="lookup_native",
            signature="void Function(int)",
            filepath="lib/ffi.dart",
            line=25
        )
        ffi_surface = dart_surface.to_ffi_surface()

        assert isinstance(ffi_surface, FfiSurface)
        assert ffi_surface.symbol_name == "lookup_native"
        assert ffi_surface.signature == "void Function(int)"
        assert ffi_surface.filepath == "lib/ffi.dart"
        assert ffi_surface.language == "dart"


class TestFfiMatcherIntegration:
    """Tests that Dart FFI surfaces work with FfiMatcher."""

    def test_dart_surface_matches_rust_surface(self):
        """Dart FfiSurface can be matched with Rust FfiSurface."""
        dart_surface = FfiSurface(
            symbol_name="process_data",
            signature="void Function(int)",
            filepath="lib/ffi.dart",
            language="dart"
        )
        rust_surface = FfiSurface(
            symbol_name="process_data",
            signature="void Function(int)",
            filepath="src/lib.rs",
            language="rust"
        )

        matcher = FfiMatcher()
        matches = matcher.match([dart_surface], [rust_surface])

        assert len(matches) == 1
        assert matches[0].confidence == 1.0
        assert matches[0].match_type == "name+signature"
        assert "dart" in matches[0].source_symbol
        assert "rust" in matches[0].target_symbol

    def test_dart_surface_symbol_id_format(self):
        """Dart FfiSurface produces correct symbol_id format."""
        dart_surface = FfiSurface(
            symbol_name="process_data",
            signature="void Function(int)",
            filepath="lib/ffi.dart",
            language="dart"
        )

        matcher = FfiMatcher()
        symbol_id = matcher._symbol_id(dart_surface)

        assert symbol_id == "dart::lib/ffi.dart::process_data"


class TestDartDataflowTracer:
    """Tests for the DartDataflowTracer."""

    def test_trace_returns_empty_when_no_path(self, tmp_path):
        """Returns empty list when no path exists."""
        arch_dir = tmp_path / ".arch"
        db = DartAnalyzerDB(arch_dir)
        db.initialize()

        tracer = DartDataflowTracer(tmp_path, db, repository=None)
        steps = tracer.trace("source_func", "sink_func")
        assert steps == []

    def test_trace_uses_cached_path(self, tmp_path):
        """Uses cached dataflow path when available."""
        arch_dir = tmp_path / ".arch"
        db = DartAnalyzerDB(arch_dir)
        db.initialize()

        # Add symbols to resolve locations
        db.upsert_resolved_symbol(
            symbol_id="source_func",
            filepath="lib/main.dart",
            kind="Function",
            type_name="void",
            return_type="void",
            parameters="()",
            is_nullable=False,
            line=10,
            col=0
        )
        db.upsert_resolved_symbol(
            symbol_id="sink_func",
            filepath="lib/utils.dart",
            kind="Function",
            type_name="void",
            return_type="void",
            parameters="()",
            is_nullable=False,
            line=20,
            col=0
        )

        # Cache a path
        db.cache_dataflow_path("source_func", "sink_func",
                              ["source_func", "sink_func"], 2)

        tracer = DartDataflowTracer(tmp_path, db, repository=None)
        steps = tracer.trace("source_func", "sink_func")

        assert len(steps) == 2
        assert steps[0].symbol == "source_func"
        assert steps[1].symbol == "sink_func"


class TestFfiExtractorIntegration:
    """Tests for FfiExtractor with dart_analyzer backend."""

    def test_extractor_with_dart_analyzer(self, tmp_path):
        """FfiExtractor can use dart_analyzer as backend."""
        from engines.ffi_extractor import FfiExtractor

        arch_dir = tmp_path / ".arch"
        db = DartAnalyzerDB(arch_dir)
        db.initialize()

        # Add FFI surface
        db.upsert_ffi_surface(
            surface_id="surface_123",
            symbol_id="my_lib::native_func",
            ffi_type="lookup",
            native_name="native_function",
            dart_name="lookup_native",
            signature="void Function(int)",
            filepath="lib/ffi.dart",
            line=25
        )

        # Create wrapper with mocked analyzer
        wrapper = MagicMock(spec=DartAnalyzerWrapper)
        wrapper.is_available.return_value = True
        wrapper.detect_ffi.return_value = [
            FfiSurface(
                symbol_name="lookup_native",
                signature="void Function(int)",
                filepath="lib/ffi.dart",
                language="dart"
            )
        ]

        extractor = FfiExtractor(codeql_wrapper=None, dart_analyzer=wrapper)
        surfaces = extractor.extract_all(tmp_path, languages=["dart"])

        assert len(surfaces) == 1
        assert surfaces[0].language == "dart"
        wrapper.detect_ffi.assert_called_once()


class TestCombinedDataflowTracer:
    """Tests for the CombinedDataflowTracer (cross-language tracing)."""

    def test_combined_tracer_initialization(self, tmp_path):
        """CombinedDataflowTracer can be initialized with all backends."""
        from engines.dart_analyzer.combined_tracer import CombinedDataflowTracer

        arch_dir = tmp_path / ".arch"
        db = DartAnalyzerDB(arch_dir)
        db.initialize()

        tracer = CombinedDataflowTracer(
            project_root=tmp_path,
            arch_dir=arch_dir,
            analyzer_db=db,
            codeql_wrappers={},
            repository=None
        )

        assert tracer.analyzer_db == db
        assert tracer.codeql_wrappers == {}
        assert tracer.repository is None

    def test_combined_tracer_builds_graph_from_analyzer_db(self, tmp_path):
        """Combined tracer loads typed_edges from analyzer DB."""
        from engines.dart_analyzer.combined_tracer import CombinedDataflowTracer

        arch_dir = tmp_path / ".arch"
        db = DartAnalyzerDB(arch_dir)
        db.initialize()

        # Add typed edges to analyzer DB
        with db.session() as conn:
            conn.execute(
                "INSERT INTO typed_edges (source_id, target_id, edge_type) VALUES (?, ?, ?)",
                ("dart_func_a", "dart_func_b", "calls")
            )
            conn.execute(
                "INSERT INTO typed_edges (source_id, target_id, edge_type) VALUES (?, ?, ?)",
                ("dart_func_b", "dart_func_c", "calls")
            )

        tracer = CombinedDataflowTracer(
            project_root=tmp_path,
            arch_dir=arch_dir,
            analyzer_db=db,
            codeql_wrappers={},
            repository=None
        )

        graph = tracer._build_combined_call_graph(source_lang="dart", sink_lang="dart")

        assert "dart_func_a" in graph
        assert "dart_func_b" in graph["dart_func_a"]
        assert "dart_func_c" in graph["dart_func_b"]

    def test_combined_tracer_finds_cross_language_path(self, tmp_path):
        """Combined tracer can trace through FFI_Binds edges."""
        from engines.dart_analyzer.combined_tracer import CombinedDataflowTracer

        arch_dir = tmp_path / ".arch"
        db = DartAnalyzerDB(arch_dir)
        db.initialize()

        # Add Dart typed edges
        with db.session() as conn:
            conn.execute(
                "INSERT INTO typed_edges (source_id, target_id, edge_type) VALUES (?, ?, ?)",
                ("dart_main", "dart_ffi_call", "calls")
            )

        # Mock repository with FFI_Binds edge
        mock_repo = MagicMock()
        mock_repo.db_conn.session.return_value.__enter__ = MagicMock(return_value=MagicMock(
            execute=MagicMock(return_value=MagicMock(
                fetchall=MagicMock(return_value=[
                    ("dart_ffi_call", "rust_process", "FFI_Binds")
                ])
            ))
        ))
        mock_repo.db_conn.session.return_value.__exit__ = MagicMock(return_value=False)

        tracer = CombinedDataflowTracer(
            project_root=tmp_path,
            arch_dir=arch_dir,
            analyzer_db=db,
            codeql_wrappers={},
            repository=mock_repo
        )

        graph = tracer._build_combined_call_graph(source_lang="dart", sink_lang="rust")

        # Should have path: dart_main -> dart_ffi_call -> rust_process
        assert "dart_main" in graph
        assert "dart_ffi_call" in graph["dart_main"]
        assert "rust_process" in graph["dart_ffi_call"]

    def test_combined_tracer_resolve_locations_uses_analyzer_db(self, tmp_path):
        """Combined tracer resolves Dart symbols from analyzer DB."""
        from engines.dart_analyzer.combined_tracer import CombinedDataflowTracer

        arch_dir = tmp_path / ".arch"
        db = DartAnalyzerDB(arch_dir)
        db.initialize()

        # Add resolved symbol (use .dart extension for language detection)
        db.upsert_resolved_symbol(
            symbol_id="lib/main.dart::dart_func",
            filepath="lib/main.dart",
            kind="Function",
            type_name="void",
            return_type="void",
            parameters="()",
            is_nullable=False,
            line=42,
            col=0
        )

        tracer = CombinedDataflowTracer(
            project_root=tmp_path,
            arch_dir=arch_dir,
            analyzer_db=db,
            codeql_wrappers={},
            repository=None
        )

        steps = tracer._resolve_locations(["lib/main.dart::dart_func"])

        assert len(steps) == 1
        assert steps[0].symbol == "lib/main.dart::dart_func"
        assert steps[0].filepath == "lib/main.dart"
        assert steps[0].line == 42
        assert steps[0].language == "dart"

    def test_combined_tracer_detects_language(self, tmp_path):
        """Combined tracer detects language from symbol ID."""
        from engines.dart_analyzer.combined_tracer import CombinedDataflowTracer

        tracer = CombinedDataflowTracer(
            project_root=tmp_path,
            arch_dir=tmp_path / ".arch",
            analyzer_db=None,
            codeql_wrappers={},
            repository=None
        )

        assert tracer._detect_language_from_symbol("my_func.dart") == "dart"
        assert tracer._detect_language_from_symbol("my_func.rs") == "rust"
        assert tracer._detect_language_from_symbol("ffi_bridge") == "ffi"
        assert tracer._detect_language_from_symbol("unknown_func") == "unknown"
