import hashlib
from unittest.mock import patch
from setup.initializer import initialize_workspace
from db.connection import DbConnection
from db.repository import Repository
from change_tracker.tracker import ChangeTracker
from engines.scip.wrapper import ingest_index

def setup_workspace(tmp_path):
    initialize_workspace(tmp_path)
    db_conn = DbConnection(tmp_path / ".arch" / "arch.db")
    repository = Repository(db_conn)
    return repository, db_conn, tmp_path

def test_calculate_sha256_existing_file(tmp_path):
    file_path = tmp_path / "test.txt"
    content = b"hello world"
    file_path.write_bytes(content)

    expected_hash = hashlib.sha256(content).hexdigest()
    assert ChangeTracker.calculate_sha256(file_path) == expected_hash

def test_calculate_sha256_non_existent_file(tmp_path):
    file_path = tmp_path / "does_not_exist.txt"
    assert ChangeTracker.calculate_sha256(file_path) == "initial_hash"

def test_calculate_sha256_directory(tmp_path):
    dir_path = tmp_path / "subdir"
    dir_path.mkdir()
    assert ChangeTracker.calculate_sha256(dir_path) == "initial_hash"

def test_calculate_sha256_permission_error(tmp_path):
    file_path = tmp_path / "test.txt"
    file_path.write_text("dummy")

    with patch("builtins.open", side_effect=PermissionError("Permission denied")):
        assert ChangeTracker.calculate_sha256(file_path) == "initial_hash"

def test_get_config_hash(tmp_path):
    _, db_conn, root = setup_workspace(tmp_path)
    config_path = root / ".arch" / "config.json"
    
    expected_hash = hashlib.sha256(config_path.read_bytes()).hexdigest()
    assert ChangeTracker.get_config_hash(root) == expected_hash
    db_conn.close()

def test_config_changed_scenarios(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)

    # Scenario 1: No config hash stored in system_metadata yet
    assert ChangeTracker.check_config_changed(root, repository) is True

    # Scenario 2: stored hash matches current hash
    current_hash = ChangeTracker.get_config_hash(root)
    with db_conn.session() as conn:
        conn.execute(
            "INSERT INTO system_metadata (key, value) VALUES ('config_hash', ?)",
            (current_hash,)
        )
    assert ChangeTracker.check_config_changed(root, repository) is False

    # Scenario 3: stored hash differs (config modified)
    with db_conn.session() as conn:
        conn.execute(
            "UPDATE system_metadata SET value = 'different_hash' WHERE key = 'config_hash'"
        )
    assert ChangeTracker.check_config_changed(root, repository) is True

    db_conn.close()

def test_update_config_hash(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)
    
    current_hash = ChangeTracker.get_config_hash(root)

    # Initially, it's not stored
    with db_conn.session() as conn:
        res = conn.execute("SELECT value FROM system_metadata WHERE key = 'config_hash'").fetchone()
        assert res is None

    # Call update
    ChangeTracker.update_config_hash(root, repository)

    with db_conn.session() as conn:
        res = conn.execute("SELECT value FROM system_metadata WHERE key = 'config_hash'").fetchone()
        assert res is not None
        assert res[0] == current_hash

    # Call update again with a different hash value to test ON CONFLICT DO UPDATE
    config_path = root / ".arch" / "config.json"
    config_path.write_text('{"modified": true}')
    new_hash = ChangeTracker.get_config_hash(root)
    assert new_hash != current_hash

    ChangeTracker.update_config_hash(root, repository)

    with db_conn.session() as conn:
        res = conn.execute("SELECT value FROM system_metadata WHERE key = 'config_hash'").fetchone()
        assert res is not None
        assert res[0] == new_hash

    db_conn.close()

def test_deleted_file_cleanup(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)

    # 1. Insert files into files table (mocked)
    repository.workspace.upsert_file('lib/ui/widget.dart', 'hash111', 'dart')
    repository.workspace.upsert_file('lib/ui/button.dart', 'hash222', 'dart')
    repository.workspace.upsert_file('src/main.rs', 'hash333', 'rust')

    # Verify they exist
    assert repository.workspace.get_file('lib/ui/widget.dart') is not None
    assert repository.workspace.get_file('lib/ui/button.dart') is not None
    assert repository.workspace.get_file('src/main.rs') is not None

    # 2. Mock a SCIP index where lib/ui/button.dart has been deleted.
    parsed_data = {
        "metadata": {
            "project_root": str(root),
            "tool_name": "scip_dart",
            "tool_version": "0.1.0"
        },
        "symbols": {
            "widget_symbol": {
                "symbol": "widget_symbol",
                "filepath": "lib/ui/widget.dart",
                "kind": "Class",
                "signature": "class Widget",
                "docstring": "",
                "body_hash": ""
            }
        },
        "occurrences": [
            {
                "symbol": "widget_symbol",
                "filepath": "lib/ui/widget.dart",
                "start_line": 1,
                "start_col": 1,
                "end_line": 10,
                "end_col": 1,
                "role": 1
            }
        ],
        "edges": []
    }

    # Create physical file lib/ui/widget.dart so hashing succeeds
    widget_path = root / "lib" / "ui" / "widget.dart"
    widget_path.parent.mkdir(parents=True, exist_ok=True)
    widget_path.write_text("class Widget {}")

    ingest_index(repository, parsed_data, project_root=root)

    # Verify widget.dart and main.rs exist, but button.dart was cleaned up
    assert repository.workspace.get_file('lib/ui/widget.dart') is not None
    assert repository.workspace.get_file('src/main.rs') is not None
    assert repository.workspace.get_file('lib/ui/button.dart') is None

    db_conn.close()


def test_transitive_invalidation(tmp_path):
    from change_tracker.invalidation import expand_changed_files
    repository, db_conn, root = setup_workspace(tmp_path)

    # Insert symbols across two files: util.dart defines helper, main.dart calls helper
    repository.graph.upsert_symbol(
        symbol="pkg::util::helper()",
        filepath="lib/util.dart",
        kind="Function",
        signature="void helper()",
        docstring="",
        body_hash="hash1"
    )
    repository.graph.upsert_symbol(
        symbol="pkg::main::run()",
        filepath="lib/main.dart",
        kind="Function",
        signature="void run()",
        docstring="",
        body_hash="hash2"
    )
    # Edge: main calls util
    repository.graph.add_edge(source="pkg::main::run()", target="pkg::util::helper()", relation="Calls")

    # Case 1: Interface (signature) did not change -> no expansion
    new_symbols_same = {
        "pkg::util::helper()": {
            "symbol": "pkg::util::helper()",
            "filepath": "lib/util.dart",
            "signature": "void helper()"
        }
    }
    expanded = expand_changed_files(repository, ["lib/util.dart"], new_symbols=new_symbols_same, max_depth=1)
    assert expanded == {"lib/util.dart"}

    # Case 2: Interface (signature) changed -> invalidates lib/main.dart
    new_symbols_changed = {
        "pkg::util::helper()": {
            "symbol": "pkg::util::helper()",
            "filepath": "lib/util.dart",
            "signature": "int helper(int x)"
        }
    }
    expanded = expand_changed_files(repository, ["lib/util.dart"], new_symbols=new_symbols_changed, max_depth=1)
    assert expanded == {"lib/util.dart", "lib/main.dart"}

    # Case 3: Calling without new_symbols defaults to invalidating dependents
    expanded_direct = expand_changed_files(repository, ["lib/util.dart"], max_depth=1)
    assert expanded_direct == {"lib/util.dart", "lib/main.dart"}

    db_conn.close()
