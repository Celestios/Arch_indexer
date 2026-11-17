import pytest
from pathlib import Path
from db.connection import DbConnection
from db.repository import Repository
from auditor.analyzer import Auditor
from auditor.compiler import ContextCompiler
from interface.formatters import format_lookup_symbol, format_context_results
from setup.initializer import initialize_workspace


def test_symbol_classification_badge_rendering():
    exact_symbol = ("pkg/Foo#bar().", "src/bar.py", "Method", "def bar()", "Doc", "hash1", 5, "pkg/Foo#", '{"layer": "Domain", "tier": 2}')
    occurrences = [("src/bar.py", 10, 10, 1)]
    edges = []
    lookup_md = format_lookup_symbol(exact_symbol, occurrences, edges)
    assert "[layer: Domain, tier: 2]" in lookup_md
    assert "- **Classification**: `[layer: Domain, tier: 2]`" in lookup_md

    symbols = [
        {
            "symbol": "pkg/Foo#bar().",
            "signature": "def bar()",
            "docstring": "Doc",
            "kind": "Method",
            "classification": '{"layer": "Domain", "tier": 2}'
        }
    ]
    symbol_to_lines = {"pkg/Foo#bar().": (10, 15)}
    context_md = format_context_results("src/bar.py", symbols, symbol_to_lines)
    assert "[layer: Domain, tier: 2]" in context_md


def test_format_context_results_tree_hierarchy():
    symbols = [
        {
            "symbol": "db/connection/DEFAULT_DB_PATH.",
            "signature": "DEFAULT_DB_PATH = Path(__file__).parent / 'arch.db'",
            "docstring": "pathlib.Path",
            "kind": "Variable",
            "classification": None,
        },
        {
            "symbol": "db/connection/DbConnection#",
            "signature": "class DbConnection:",
            "docstring": "Manages DuckDB database connections and initialization.",
            "kind": "Class",
            "classification": None,
        },
        {
            "symbol": "db/connection/DbConnection#__init__().",
            "signature": "def __init__(self, db_path: Path):",
            "docstring": "def __init__(",
            "kind": "Method",
            "classification": None,
        },
        {
            "symbol": "db/connection/DbConnection#db_path.",
            "signature": "self.db_path = db_path",
            "docstring": "(variable) db_path: Path",
            "kind": "Field",
            "classification": None,
        },
        {
            "symbol": "db/connection/DbConnection#get_connection().",
            "signature": "def get_connection(self) -> duckdb.DuckDBPyConnection:",
            "docstring": "Creates and returns a connection to the database.",
            "kind": "Method",
            "classification": None,
        },
    ]
    symbol_to_lines = {
        "db/connection/DEFAULT_DB_PATH.": (7, 7),
        "db/connection/DbConnection#": (9, 149),
        "db/connection/DbConnection#__init__().": (14, 17),
        "db/connection/DbConnection#db_path.": (15, 15),
        "db/connection/DbConnection#get_connection().": (19, 33),
    }

    res = format_context_results("src/db/connection.py", symbols, symbol_to_lines)

    # 1. Constants section exists and strips module prefix
    assert "### Constants & Variables" in res
    assert "- `DEFAULT_DB_PATH` [L7]" in res

    # 2. Class section exists and nests members
    assert "### Classes" in res
    assert "- **class DbConnection** [L9-149]" in res
    assert "*Docstring*: Manages DuckDB database connections and initialization." in res

    # 3. Fields clustered and clean
    assert "*Fields*: `db_path = db_path` [L15]" in res

    # 4. Methods nested under class with inline signature and real docstring
    assert "- `def __init__(self, db_path: Path)` [L14-17]" in res
    assert "- `def get_connection(self) -> duckdb.DuckDBPyConnection` [L19-33]" in res
    assert "Creates and returns a connection to the database." in res

    # 5. Fake docstrings pruned
    assert "*Docstring*: def __init__(" not in res
    assert "pathlib.Path" not in res
    assert "(variable)" not in res


def test_counterfactual_fix_suggestion(tmp_path):
    root = initialize_workspace(tmp_path)
    db_conn = DbConnection(root / "arch.db")
    repo = Repository(db_conn)

    # Presentation -> Infrastructure violation
    # Domain is barrier
    # UserRepository (in Domain) already calls DbConnection
    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash)
            VALUES
                ('ui/Widget#render().', 'lib/ui/widget.dart', 'Method', 'void render()', '', 'h1'),
                ('domain/UserRepository#save().', 'lib/domain/user_repo.dart', 'Method', 'void save()', '', 'h2'),
                ('infra/DbConnection#query().', 'lib/infra/db.dart', 'Method', 'void query()', '', 'h3')
        """)
        conn.execute("""
            INSERT INTO edges (source, target, relation)
            VALUES
                ('ui/Widget#render().', 'infra/DbConnection#query().', 'Calls'),
                ('domain/UserRepository#save().', 'infra/DbConnection#query().', 'Calls')
        """)

    config = {
        "lib": {
            "automatic_fields": {
                "layer": {
                    "values": ["Presentation", "Domain", "Infrastructure"],
                    "default": "Domain",
                    "assignment_rules": [
                        {"value": "Presentation", "conditions": {"path_prefix": "lib/ui"}},
                        {"value": "Domain", "conditions": {"path_prefix": "lib/domain"}},
                        {"value": "Infrastructure", "conditions": {"path_prefix": "lib/infra"}}
                    ],
                    "barriers": ["Domain"],
                    "rules": [
                        {
                            "rule_type": "dependency_check",
                            "source": "Presentation",
                            "target": "Infrastructure",
                            "message": "Presentation cannot call Infrastructure"
                        }
                    ]
                }
            }
        }
    }
    import json
    (root / "config.json").write_text(json.dumps(config), encoding="utf-8")

    auditor = Auditor(repo, tmp_path)
    violations = auditor.run_audit()

    assert len(violations) >= 1
    v_msg = violations[0]["message"]
    assert "Presentation cannot call Infrastructure" in v_msg
    assert "Suggested Fix" in v_msg
    assert "UserRepository" in v_msg

    # Verify classification was persisted to symbols table
    sym = repo.symbols.get_symbol("ui/Widget#render().")
    assert sym is not None
    assert "Presentation" in sym["classification"]

    db_conn.close()
