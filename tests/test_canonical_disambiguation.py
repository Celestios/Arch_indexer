import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from utils.helpers import is_auxiliary_path, score_definition_candidate
from engines.scip.parser import ScipParser


class TestAuxiliaryPathMatcher:
    def test_rust_test_paths(self):
        assert is_auxiliary_path("rust/centrode_daemon/tests/engine_management.rs") is True
        assert is_auxiliary_path("tests/daemon_services.rs") is True
        assert is_auxiliary_path("rust/centrode_daemon/src/lib.rs") is False
        assert is_auxiliary_path("rust/centrode_daemon/src/domain/types.rs") is False

    def test_dart_test_paths(self):
        assert is_auxiliary_path("test/features/auth_test.dart") is True
        assert is_auxiliary_path("lib/features/auth/login_test.dart") is True
        assert is_auxiliary_path("lib/features/auth/login.dart") is False

    def test_js_ts_python_test_paths(self):
        assert is_auxiliary_path("src/components/button.test.ts") is True
        assert is_auxiliary_path("spec/models/user_spec.rb") is True
        assert is_auxiliary_path("tests/test_parser.py") is True
        assert is_auxiliary_path("src/utils/helpers.py") is False

    def test_benchmark_and_example_paths(self):
        assert is_auxiliary_path("benches/lexer_bench.rs") is True
        assert is_auxiliary_path("examples/simple_daemon.rs") is True
        assert is_auxiliary_path("samples/demo.dart") is True
        assert is_auxiliary_path("src/server.rs") is False

    def test_none_or_empty(self):
        assert is_auxiliary_path(None) is False
        assert is_auxiliary_path("") is False


class TestDefinitionScoring:
    def test_primary_beats_auxiliary(self):
        primary_defn = {
            "symbol": "my_sym",
            "filepath": "src/lib.rs",
            "signature": "pub fn run()",
            "docstring": "Runs the system",
        }
        test_defn = {
            "symbol": "my_sym",
            "filepath": "tests/test_run.rs",
            "signature": "pub fn run()",
            "docstring": "Runs the system",
        }
        score_primary = score_definition_candidate(primary_defn, start_line=1, end_line=10)
        score_test = score_definition_candidate(test_defn, start_line=1, end_line=10)
        assert score_primary > score_test

    def test_richer_signature_and_docstring_wins(self):
        rich_defn = {
            "symbol": "my_sym",
            "filepath": "src/service.rs",
            "signature": "pub struct Service",
            "docstring": "Detailed docs",
        }
        bare_defn = {
            "symbol": "my_sym",
            "filepath": "src/service.rs",
            "signature": None,
            "docstring": "",
        }
        score_rich = score_definition_candidate(rich_defn, start_line=1, end_line=5)
        score_bare = score_definition_candidate(bare_defn, start_line=1, end_line=5)
        assert score_rich > score_bare

    def test_external_stub_has_lowest_score(self):
        external_stub = {
            "symbol": "external_sym",
            "filepath": None,
            "signature": None,
            "docstring": "",
        }
        local_defn = {
            "symbol": "external_sym",
            "filepath": "src/domain.rs",
            "signature": "pub struct Domain",
            "docstring": "",
        }
        assert score_definition_candidate(local_defn) > score_definition_candidate(external_stub)


class TestCanonicalDisambiguationInParser:
    @patch("engines.scip.parser.scip_pb2.Index")
    def test_test_file_encountered_first_then_primary_file(self, mock_index_cls, tmp_path):
        scip_file = tmp_path / "index.scip"
        scip_file.write_bytes(b"dummy")

        src_file = tmp_path / "src" / "lib.rs"
        src_file.parent.mkdir(parents=True, exist_ok=True)
        src_file.write_text("/// Primary crate root\npub mod domain;\n", encoding="utf-8")

        test_file = tmp_path / "tests" / "integration.rs"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("// Test runner root\nuse my_crate;\n", encoding="utf-8")

        mock_index = MagicMock()
        mock_index_cls.return_value = mock_index
        mock_index.external_symbols = []

        crate_sym = "cargo my_crate 0.1.0 my_crate/"

        # Doc 1: Test file defines crate_sym
        doc_test = MagicMock()
        doc_test.relative_path = "tests/integration.rs"
        doc_test.symbols = []
        occ_test = MagicMock()
        occ_test.symbol = crate_sym
        occ_test.symbol_roles = 1  # Definition
        occ_test.range = [0, 0, 1, 0]
        doc_test.occurrences = [occ_test]

        # Doc 2: Src file defines crate_sym
        doc_src = MagicMock()
        doc_src.relative_path = "src/lib.rs"
        doc_src.symbols = []
        occ_src = MagicMock()
        occ_src.symbol = crate_sym
        occ_src.symbol_roles = 1  # Definition
        occ_src.range = [1, 0, 1, 15]
        doc_src.occurrences = [occ_src]

        # Index has test doc first, then src doc
        mock_index.documents = [doc_test, doc_src]

        parsed = ScipParser.parse_index(scip_file, tmp_path)

        # The canonical symbol must resolve to src/lib.rs despite test doc being parsed first
        assert parsed["symbols"][crate_sym]["filepath"] == "src/lib.rs"
        assert parsed["symbols"][crate_sym]["docstring"] == "Primary crate root"

        # Both occurrences are preserved
        crate_occs = [o for o in parsed["occurrences"] if o["symbol"] == crate_sym]
        assert len(crate_occs) == 2
