import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from engines.scip.parser import (
    extract_source_signature,
    extract_source_docstring,
    ScipParser,
)
from utils.helpers import infer_scip_kind


class TestScipSynthesizerSignatures:
    def test_extract_rust_signature(self):
        lines = [
            "/// Documentation for daemon\n",
            "#[derive(Debug, Clone)]\n",
            "pub struct DaemonHandle {\n",
            "    pub id: String,\n",
            "}\n",
        ]
        # start_line = 3 (pub struct DaemonHandle)
        sig = extract_source_signature(lines, start_line=3, end_line=5)
        assert sig == "pub struct DaemonHandle"

    def test_extract_dart_signature(self):
        lines = [
            "/// Client interaction service\n",
            "abstract class ClientInteractionService {\n",
            "  void execute();\n",
            "}\n",
        ]
        # start_line = 2 (abstract class ClientInteractionService)
        sig = extract_source_signature(lines, start_line=2, end_line=4)
        assert sig == "abstract class ClientInteractionService"

    def test_extract_python_signature(self):
        lines = [
            "# Core dispatch function\n",
            "def dispatch_event(\n",
            "    name: str,\n",
            "    payload: dict\n",
            ") -> bool:\n",
            "    return True\n",
        ]
        # start_line = 2, multiline signature
        sig = extract_source_signature(lines, start_line=2, end_line=5)
        assert "def dispatch_event(" in sig
        assert "-> bool:" in sig

    def test_extract_single_line_statement(self):
        lines = ["const int MAX_RETRIES = 5;\n"]
        sig = extract_source_signature(lines, start_line=1, end_line=1)
        assert sig == "const int MAX_RETRIES = 5;"

    def test_invalid_line_returns_none(self):
        lines = ["line 1\n"]
        assert extract_source_signature(lines, start_line=0, end_line=1) is None
        assert extract_source_signature(lines, start_line=5, end_line=5) is None
        assert extract_source_signature([], start_line=1, end_line=1) is None


class TestScipSynthesizerDocstrings:
    def test_extract_rust_triple_slash_docstring(self):
        lines = [
            "/// First doc line\n",
            "/// Second doc line\n",
            "pub fn start() {}\n",
        ]
        docs = extract_source_docstring(lines, start_line=3)
        assert docs == "First doc line\nSecond doc line"

    def test_extract_dart_docstring(self):
        lines = [
            "/// Service implementation\n",
            "class MyService {}\n",
        ]
        docs = extract_source_docstring(lines, start_line=2)
        assert docs == "Service implementation"

    def test_extract_c_block_docstring(self):
        lines = [
            "/**\n",
            " * Computes hash\n",
            " * @return hash value\n",
            " */\n",
            "int compute();\n",
        ]
        docs = extract_source_docstring(lines, start_line=5)
        assert "Computes hash" in docs
        assert "@return hash value" in docs

    def test_extract_python_hash_comments(self):
        lines = [
            "# Utility function\n",
            "# Performs parsing\n",
            "def parse():\n",
        ]
        docs = extract_source_docstring(lines, start_line=3)
        assert docs == "Utility function\nPerforms parsing"

    def test_no_preceding_doc_returns_empty(self):
        lines = [
            "let x = 1;\n",
            "pub fn start() {}\n",
        ]
        assert extract_source_docstring(lines, start_line=2) == ""


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
