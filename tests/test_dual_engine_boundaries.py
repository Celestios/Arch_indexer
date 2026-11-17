import pytest
from engines.treesitter.loader import TreesitterLoader
from engines.treesitter.extractor import TreesitterExtractor
from engines.treesitter.folding import CodeFolder
from engines.treesitter.metrics import MetricsCalculator


def test_treesitter_loader_dart_extension():
    lang = TreesitterLoader.detect_language("lib/main.dart")
    assert lang == "dart"


def test_rust_doc_comment_with_intervening_attributes():
    rs_code = b"""
    /// FFI exported entrypoint.
    #[no_mangle]
    pub extern "C" fn rust_bridge_init() -> i32 {
        42
    }
    """
    syms = TreesitterExtractor.extract_symbols_from_file("src/lib.rs", source=rs_code)
    assert len(syms) == 1
    assert syms[0].docstring == "FFI exported entrypoint."
    assert "#[no_mangle]" in syms[0].annotations["decorators"]


def test_typescript_exported_class_preserves_jsdoc():
    ts_code = b"""
    /** Manages client state. */
    export class StateManager {
        run(): void {}
    }
    """
    syms = TreesitterExtractor.extract_symbols_from_file("src/state.ts", source=ts_code)
    cls_sym = next(s for s in syms if s.kind == "Class")
    assert cls_sym.docstring == "Manages client state."


def test_python_code_folding_no_extra_blank_line():
    py_code = "def compute(x: int) -> int:\n    return x + 1\n"
    folded = CodeFolder.fold_code(py_code, "python")
    assert folded.splitlines() == ["def compute(x: int) -> int:", "    ..."]


def test_metrics_branch_nodes_and_nesting():
    assert "ternary_expression" in MetricsCalculator.BRANCH_NODE_TYPES
    assert "for_expression" in MetricsCalculator.BRANCH_NODE_TYPES
    assert "while_expression" in MetricsCalculator.BRANCH_NODE_TYPES
    assert "switch_statement" not in MetricsCalculator.BRANCH_NODE_TYPES
    assert "switch_statement" in MetricsCalculator.NESTING_NODE_TYPES
