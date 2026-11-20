import pytest
from setup.initializer import initialize_workspace
from db.connection import DbConnection
from db.repository import Repository
from engines.scip.wrapper import ScipWrapper

def setup_workspace(tmp_path):
    initialize_workspace(tmp_path)
    db_conn = DbConnection(tmp_path / ".arch" / "arch.db")
    repository = Repository(db_conn)
    return repository, db_conn, tmp_path

@pytest.mark.skip(reason="Edge weight calculation removed from ScipWrapper in eeca669 (assigned during audit phase)")
def test_edge_weight_calculation():
    config = {
        "lib/ui": {
            "automatic_fields": {
                "layer": {
                    "default": "Presentation"
                }
            }
        },
        "lib/engine": {
            "automatic_fields": {
                "layer": {
                    "default": "Application",
                    "rules": [
                        {
                            "source": "Application",
                            "target": "Infrastructure",
                            "message": "Error calling infra",
                            "severity": "Error"
                        }
                    ]
                }
            }
        },
        "lib/infra": {
            "automatic_fields": {
                "layer": {
                    "default": "Infrastructure"
                }
            }
        }
    }

    # Same layer boost (Presentation -> Presentation)
    w = ScipWrapper.calculate_edge_weight("lib/ui/main.dart", "lib/ui/widgets.dart", config)
    assert w == 1.5

    # Cross layer without rule restriction (Presentation -> Application)
    w = ScipWrapper.calculate_edge_weight("lib/ui/main.dart", "lib/engine/logic.dart", config)
    assert w == 1.0

    # Cross layer with violation restriction (Application -> Infrastructure)
    w = ScipWrapper.calculate_edge_weight("lib/engine/logic.dart", "lib/infra/db.dart", config)
    assert w == 0.5

def test_connection_weights_recalculation(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)
    
    # Insert symbols
    repository.graph.upsert_symbol("sym_a", "lib/a.dart", "Function", "void a()", "docs a", "hash_a", 0)
    repository.graph.upsert_symbol("sym_b", "lib/b.dart", "Function", "void b()", "docs b", "hash_b", 0)
    repository.graph.upsert_symbol("sym_c", "lib/c.dart", "Function", "void c()", "docs c", "hash_c", 0)

    # Insert edges
    repository.graph.add_edge("sym_a", "sym_b", "Calls", 1.0)
    repository.graph.add_edge("sym_b", "sym_c", "Calls", 1.5)

    # Recalculate
    repository.graph.recalculate_connection_weights()

    # Verify connection weights
    # sym_a has 1 outgoing edge
    sym_a = repository.graph.get_symbol("sym_a")
    assert sym_a["connection_weight"] == 1

    # sym_b has 1 incoming + 1 outgoing = 2 edges
    sym_b = repository.graph.get_symbol("sym_b")
    assert sym_b["connection_weight"] == 2

    # sym_c has 1 incoming edge
    sym_c = repository.graph.get_symbol("sym_c")
    assert sym_c["connection_weight"] == 1

    db_conn.close()

def test_shrink_guard(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)
    
    # 1. Populate initial files and symbols
    files = [{"filepath": "lib/a.dart", "sha256": "h1", "language": "dart"}]
    repository.workspace.upsert_files_bulk(files)
    
    symbols = [
        {"symbol": "sym1", "filepath": "lib/a.dart", "kind": "Function", "signature": "", "docstring": "", "body_hash": "", "connection_weight": 0},
        {"symbol": "sym2", "filepath": "lib/a.dart", "kind": "Function", "signature": "", "docstring": "", "body_hash": "", "connection_weight": 0}
    ]
    repository.graph.upsert_symbols_bulk(symbols)

    # Physically create the file lib/a.dart on disk so it exists (guard checks for physical existence)
    a_file = root / "lib" / "a.dart"
    a_file.parent.mkdir(parents=True, exist_ok=True)
    a_file.write_text("void a() {}")

    # 2. Try to ingest empty parsed data without force (should raise ValueError due to shrink guard)
    parsed_data = {
        "occurrences": [],
        "symbols": {},
        "edges": [],
        "files": ["lib/a.dart"]
    }

    try:
        ScipWrapper.ingest_index(repository, parsed_data, project_root=root, force=False)
        assert False, "Should raise ValueError due to shrink guard"
    except ValueError as e:
        assert "Shrink Guard" in str(e)

    # 3. Try to ingest empty parsed data with force (should succeed and delete everything)
    ScipWrapper.ingest_index(repository, parsed_data, project_root=root, force=True)
    
    # Verify no symbols left
    with repository.db_conn.session() as conn:
        count = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
        assert count == 0

    # 4. Verify minor drop is tolerated (e.g. 100 symbols -> 99 symbols)
    symbols_100 = [
        {"symbol": f"sym_{i}", "filepath": "lib/a.dart", "kind": "Function", "signature": "", "docstring": "", "body_hash": "", "connection_weight": 0}
        for i in range(100)
    ]
    repository.graph.upsert_symbols_bulk(symbols_100)
    
    # Change the file content so its hash changes and it gets re-ingested
    a_file.write_text("void a() { int x; }")
    
    parsed_data_99 = {
        "occurrences": [],
        "symbols": {
            f"sym_{i}": {"symbol": f"sym_{i}", "filepath": "lib/a.dart", "kind": "Function", "signature": "", "docstring": "", "body_hash": ""}
            for i in range(99)
        },
        "edges": [],
        "files": ["lib/a.dart"]
    }
    # This should succeed without raising ValueError
    ScipWrapper.ingest_index(repository, parsed_data_99, project_root=root, force=False)
    
    with repository.db_conn.session() as conn:
        count = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
        assert count == 99

    db_conn.close()
