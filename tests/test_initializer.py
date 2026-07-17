import json
from setup.initializer import initialize_workspace


def test_initialize_creates_arch_dir(tmp_path):
    arch_dir = initialize_workspace(tmp_path)
    assert arch_dir.exists()
    assert (arch_dir / "config.json").exists()
    assert (arch_dir / "arch.db").exists()


def test_initialize_preserves_existing_config(tmp_path):
    arch_dir = tmp_path / ".arch"
    arch_dir.mkdir()
    config = arch_dir / "config.json"
    config.write_text('{"custom": true}')

    initialize_workspace(tmp_path)

    data = json.loads(config.read_text())
    assert data == {"custom": True}


def test_initialize_loads_compliance_rules(tmp_path):
    initialize_workspace(tmp_path)

    from db.connection import DbConnection

    db_conn = DbConnection(tmp_path / ".arch" / "arch.db")

    with db_conn.session() as conn:
        res = conn.execute("SELECT COUNT(*) FROM compliance_rules").fetchone()
        assert res[0] == 0

    db_conn.close()
