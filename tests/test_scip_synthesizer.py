import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from engines.scip.parser import ScipParser
from utils.helpers import infer_scip_kind


class TestScipCallsEdgeCallLine:
    @patch("engines.scip.parser.scip_pb2.Index")
    def test_calls_edge_records_call_line(self, mock_index_cls, tmp_path):
        scip_file = tmp_path / "index.scip"
        scip_file.write_bytes(b"dummy")

        mock_index = MagicMock()
        mock_index_cls.return_value = mock_index
        mock_index.external_symbols = []

        doc = MagicMock()
        doc.relative_path = "src/service.py"
        doc.symbols = []

        callee_sym = MagicMock()
        callee_sym.symbol = "scip-python python test 0.1.0 pkg/Callee#execute()."
        callee_sym.kind = 3
        callee_sym.documentation = []
        doc.symbols = [callee_sym]

        caller_def = MagicMock()
        caller_def.symbol = "scip-python python test 0.1.0 pkg/Caller#run()."
        caller_def.symbol_roles = 1
        caller_def.range = [10, 4, 25, 5]

        callee_def = MagicMock()
        callee_def.symbol = "scip-python python test 0.1.0 pkg/Callee#execute()."
        callee_def.symbol_roles = 1
        callee_def.range = [30, 4, 35, 5]

        callee_ref = MagicMock()
        callee_ref.symbol = "scip-python python test 0.1.0 pkg/Callee#execute()."
        callee_ref.symbol_roles = 0
        callee_ref.range = [15, 8, 15, 20]

        doc.occurrences = [caller_def, callee_def, callee_ref]
        mock_index.documents = [doc]

        parsed = ScipParser.parse_index(scip_file, tmp_path)

        assert len(parsed["edges"]) == 1
        edge = parsed["edges"][0]
        assert edge["source"] == "scip-python python test 0.1.0 pkg/Caller#run()."
        assert edge["target"] == "scip-python python test 0.1.0 pkg/Callee#execute()."
        assert edge["relation"] == "Calls"
        assert edge["call_line"] == 16


class TestScipDescriptorKindInference:
    def test_infer_type_class(self):
        assert infer_scip_kind("cargo centrode 0.1.0 DaemonHandle#") == "Class"

    def test_infer_method_and_function(self):
        assert infer_scip_kind("cargo centrode 0.1.0 Service#run().") == "Method"
        assert infer_scip_kind("cargo centrode 0.1.0 compute().") == "Function"
        assert infer_scip_kind("cargo centrode 0.1.0 Service#new().") == "Constructor"

    def test_infer_field_and_property(self):
        assert infer_scip_kind("cargo centrode 0.1.0 DaemonHandle#id.") == "Field"

    def test_infer_module_and_namespace(self):
        assert infer_scip_kind("cargo centrode 0.1.0 domain/types/") == "Module"

    def test_infer_type_parameter(self):
        assert infer_scip_kind("cargo centrode 0.1.0 Service#[T]:") == "TypeParameter"

    def test_infer_macro(self):
        assert infer_scip_kind("cargo centrode 0.1.0 my_macro$") == "Macro"

    def test_infer_parameter(self):
        assert infer_scip_kind("cargo centrode 0.1.0 func(param)") == "Parameter"


class TestScipMissingSymbolRecovery:
    @patch("engines.scip.parser.scip_pb2.Index")
    def test_missing_referenced_symbol_synthesized(self, mock_index_cls, tmp_path):
        scip_file = tmp_path / "index.scip"
        scip_file.write_bytes(b"dummy")

        mock_index = MagicMock()
        mock_index_cls.return_value = mock_index
        mock_index.external_symbols = []

        # Document with occurrence referencing a symbol not in document.symbols
        doc = MagicMock()
        doc.relative_path = "src/main.rs"
        doc.symbols = []

        ref_occ = MagicMock()
        ref_occ.symbol = "cargo centrode 0.1.0 UnindexedType#"
        ref_occ.symbol_roles = 0  # Reference
        ref_occ.range = [10, 5, 10, 18]

        doc.occurrences = [ref_occ]
        mock_index.documents = [doc]

        parsed = ScipParser.parse_index(scip_file, tmp_path)

        assert "cargo centrode 0.1.0 UnindexedType#" in parsed["symbols"]
        sym = parsed["symbols"]["cargo centrode 0.1.0 UnindexedType#"]
        assert sym["kind"] == "Class"
        assert sym["filepath"] is None
