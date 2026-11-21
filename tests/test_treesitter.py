"""
Unit and integration tests for the Tree-sitter AST engine.
"""
from pathlib import Path
import pytest

from engines.treesitter.loader import get_parser, get_language
from engines.treesitter.extractor import TreesitterExtractor
from engines.treesitter.folding import CodeFolder
from engines.treesitter.metrics import MetricsCalculator
from engines.treesitter.rules import StructuralRuleChecker
from engines.treesitter.annotations import AnnotationExtractor
from engines.treesitter import TreesitterEngine


def test_treesitter_loader():
    """Verify that loader functions successfully load installed parsers."""
    for lang in ("python", "rust", "typescript", "javascript"):
        parser = get_parser(lang)
        assert parser is not None, f"Failed to get parser for {lang}"
        language = get_language(lang)
        assert language is not None, f"Failed to get language for {lang}"


def test_python_symbol_extraction():
    """Verify accurate extraction of Python classes, methods, docstrings, and signatures."""
    python_code = '''
"""Module docstring."""

class UserService:
    """Manages user operations."""

    def __init__(self, db_url: str = "sqlite://"):
        self.db_url = db_url

    def find_user(
        self,
        user_id: int,
        include_inactive: bool = False,
    ) -> dict:
        """Find a user by their primary key ID."""
        return {"id": user_id}

def standalone_func(x: int) -> int:
    return x * 2
'''
    symbols = TreesitterExtractor.extract_symbols_from_file("src/services/user.py", python_code)
    sym_map = {s.name: s for s in symbols}

    assert "UserService" in sym_map
    cls_decl = sym_map["UserService"]
    assert cls_decl.kind == "Class"
    assert cls_decl.clean_symbol == "services.user.UserService"
    assert cls_decl.signature == "class UserService:"
    assert "Manages user operations." in cls_decl.docstring
    assert cls_decl.start_line == 4
    assert cls_decl.parent_symbol is None

    assert "__init__" in sym_map
    init_decl = sym_map["__init__"]
    assert init_decl.kind == "Constructor"
    assert init_decl.parent_symbol == "services.user.UserService"
    assert "def __init__(self, db_url: str = \"sqlite://\"):" in init_decl.signature

    assert "find_user" in sym_map
    method_decl = sym_map["find_user"]
    assert method_decl.kind == "Method"
    assert method_decl.parent_symbol == "services.user.UserService"
    assert "def find_user(" in method_decl.signature
    assert "user_id: int" in method_decl.signature
    assert "-> dict:" in method_decl.signature
    assert "Find a user by their primary key ID." in method_decl.docstring

    assert "standalone_func" in sym_map
    fn_decl = sym_map["standalone_func"]
    assert fn_decl.kind == "Function"
    assert fn_decl.parent_symbol is None
    assert "def standalone_func(x: int) -> int:" in fn_decl.signature


def test_rust_symbol_extraction():
    """Verify Rust struct, trait, and function item extraction."""
    rust_code = '''
/// Represents a user entity.
pub struct User {
    pub id: u64,
    pub name: String,
}

pub trait Repository {
    fn find_by_id(&self, id: u64) -> Option<User>;
}

/// Computes SHA hash.
#[no_mangle]
pub fn compute_hash(data: &[u8]) -> String {
    String::new()
}
'''
    symbols = TreesitterExtractor.extract_symbols_from_file("src/domain/user.rs", rust_code)
    sym_map = {s.name: s for s in symbols}

    assert "User" in sym_map
    assert sym_map["User"].kind == "Struct"
    assert "pub struct User" in sym_map["User"].signature
    assert "Represents a user entity." in sym_map["User"].docstring

    assert "Repository" in sym_map
    assert sym_map["Repository"].kind == "Trait"

    assert "compute_hash" in sym_map
    assert sym_map["compute_hash"].kind == "Function"
    assert "pub fn compute_hash(data: &[u8]) -> String" in sym_map["compute_hash"].signature
    assert "Computes SHA hash." in sym_map["compute_hash"].docstring


def test_typescript_symbol_extraction():
    """Verify TypeScript class, interface, and method extraction."""
    ts_code = '''
/** User interface */
export interface User {
    id: string;
    email: string;
}

export class AuthService {
    /** Authenticate user credentials */
    public async login(email: string, pass: string): Promise<User | null> {
        return null;
    }
}
'''
    symbols = TreesitterExtractor.extract_symbols_from_file("src/auth/service.ts", ts_code)
    sym_map = {s.name: s for s in symbols}

    assert "User" in sym_map
    assert sym_map["User"].kind == "Interface"
    assert "interface User" in sym_map["User"].signature
    assert "User interface" in sym_map["User"].docstring

    assert "AuthService" in sym_map
    assert sym_map["AuthService"].kind == "Class"

    assert "login" in sym_map
    assert sym_map["login"].kind == "Method"
    assert "public async login(email: string, pass: string): Promise<User | null>" in sym_map["login"].signature


def test_skeleton_code_folding():
    """Verify that CodeFolder collapses function bodies to '...' while preserving signatures and docstrings."""
    python_code = '''def calculate_total(items: list, tax: float) -> float:
    """Calculate the grand total including taxes."""
    total = sum(items)
    with_tax = total * (1.0 + tax)
    return round(with_tax, 2)
'''
    folded = CodeFolder.fold_code(python_code, "python")
    assert "def calculate_total(items: list, tax: float) -> float:" in folded
    assert "Calculate the grand total including taxes." in folded
    assert "..." in folded
    assert "sum(items)" not in folded


def test_metrics_calculator():
    """Verify cyclomatic complexity and nesting depth calculation."""
    python_code = '''def complex_decision(a, b, c):
    if a > 0:
        for x in b:
            if x == c:
                return True
    elif a < 0:
        return False
    return None
'''
    parser = get_parser("python")
    tree = parser.parse(python_code.encode("utf-8"))
    fn_node = tree.root_node.children[0]
    metrics = MetricsCalculator.calculate_metrics(fn_node, python_code.encode("utf-8"))

    # Base (1) + if (1) + for (1) + if (1) + elif (1) = 5
    assert metrics["cyclomatic_complexity"] >= 4
    assert metrics["max_nesting_depth"] >= 3
    assert metrics["loc"] == 8


def test_structural_rule_checker():
    """Verify syntactic anti-pattern detection (bare except, eval)."""
    bad_python = '''def dangerous():
    try:
        eval("2 + 2")
    except:
        pass
'''
    violations = StructuralRuleChecker.check_file("bad.py", bad_python, "python")
    rule_ids = {v["rule_id"] for v in violations}
    assert "ANTI_BARE_EXCEPT" in rule_ids
    assert "ANTI_DANGEROUS_EXEC" in rule_ids


def test_db_connection_real_file_extraction():
    """Explicitly verify that src/db/connection.py extracts DbConnection at line 9 with class signature and docstring."""
    symbols = TreesitterEngine.extract_symbols("src/db/connection.py")
    sym_map = {s.name: s for s in symbols}

    assert "DbConnection" in sym_map
    db_conn = sym_map["DbConnection"]
    assert db_conn.kind == "Class"
    assert db_conn.start_line == 9
    assert db_conn.signature == "class DbConnection:"
    assert "Manages DuckDB database connections and initialization." in db_conn.docstring
    assert db_conn.clean_symbol == "db.connection.DbConnection"

    assert "get_connection" in sym_map
    get_conn = sym_map["get_connection"]
    assert get_conn.kind == "Method"
    assert get_conn.parent_symbol == "db.connection.DbConnection"
    assert "def get_connection(self) -> duckdb.DuckDBPyConnection:" in get_conn.signature
