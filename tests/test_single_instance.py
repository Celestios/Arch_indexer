import json
import os
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

from utils.single_instance import (
    LOCK_FILE_NAME,
    _server_alive,
    acquire_server,
    check_existing,
    read_lock,
    write_lock,
)
import pytest


@pytest.fixture(autouse=True)
def isolate_global_arch_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCH_GLOBAL_DIR", str(tmp_path / "global_arch"))
    monkeypatch.delenv("ARCH_PROJECT_ROOT", raising=False)
    yield
    monkeypatch.delenv("ARCH_PROJECT_ROOT", raising=False)


def test_write_and_read_lock(tmp_path):
    arch_dir = tmp_path / ".arch"
    lock_file = write_lock(arch_dir, 1234, 8071)
    assert lock_file.exists()

    data = read_lock(arch_dir)
    assert data == {"pid": 1234, "port": 8071, "url": "http://127.0.0.1:8071"}


def test_read_lock_missing_or_corrupt(tmp_path):
    arch_dir = tmp_path / ".arch"
    assert read_lock(arch_dir) is None

    arch_dir.mkdir(parents=True, exist_ok=True)
    (arch_dir / LOCK_FILE_NAME).write_text("invalid json")
    assert read_lock(arch_dir) is None


def test_server_alive_scenarios():
    # 1. 200 OK
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_resp
    with patch("urllib.request.urlopen", return_value=mock_cm):
        assert _server_alive("http://127.0.0.1:8071") is True

    # 2. 404 Not Found (FastMCP returns 404 on root route for SSE)
    http_error_404 = urllib.error.HTTPError(
        "http://127.0.0.1:8071", 404, "Not Found", {}, None
    )
    with patch("urllib.request.urlopen", side_effect=http_error_404):
        assert _server_alive("http://127.0.0.1:8071") is True

    # 3. 500 Server Error
    http_error_500 = urllib.error.HTTPError(
        "http://127.0.0.1:8071", 500, "Server Error", {}, None
    )
    with patch("urllib.request.urlopen", side_effect=http_error_500):
        assert _server_alive("http://127.0.0.1:8071") is False

    # 4. Connection refused (URLError)
    url_error = urllib.error.URLError("Connection refused")
    with patch("urllib.request.urlopen", side_effect=url_error):
        assert _server_alive("http://127.0.0.1:8071") is False


def test_acquire_server_fresh(tmp_path):
    arch_dir = tmp_path / ".arch"
    with patch("utils.single_instance._port_open", return_value=True), patch(
        "utils.single_instance._find_open_port", return_value=8075
    ):
        url = acquire_server(arch_dir)
        assert url is None  # None means this instance acquired slot
        lock = read_lock(arch_dir)
        assert lock["pid"] == os.getpid()
        assert lock["port"] == 8075


def test_acquire_server_custom_port(tmp_path):
    arch_dir = tmp_path / ".arch"
    url = acquire_server(arch_dir, port=9099)
    assert url is None
    lock = read_lock(arch_dir)
    assert lock["port"] == 9099


def test_acquire_server_existing_alive(tmp_path):
    arch_dir = tmp_path / ".arch"
    write_lock(arch_dir, 99999, 8071)
    with patch("utils.single_instance._pid_alive", return_value=True), patch(
        "utils.single_instance._server_alive", return_value=True
    ):
        url = acquire_server(arch_dir)
        assert url == "http://127.0.0.1:8071"


def test_check_existing_cleans_stale_lock(tmp_path):
    arch_dir = tmp_path / ".arch"
    write_lock(arch_dir, 99999, 8071)
    with patch("utils.single_instance._pid_alive", return_value=False):
        url = check_existing(arch_dir)
        assert url is None
        assert not (arch_dir / LOCK_FILE_NAME).exists()


def test_stop_server_running(tmp_path):
    from utils.single_instance import stop_server

    arch_dir = tmp_path / ".arch"
    write_lock(arch_dir, 12345, 8071)
    with patch("utils.single_instance._pid_alive", return_value=True), patch(
        "utils.single_instance._kill_pid", return_value=True
    ) as mock_kill:
        stopped = stop_server(arch_dir)
        assert stopped == 12345
        mock_kill.assert_called_once_with(12345)
        assert not (arch_dir / LOCK_FILE_NAME).exists()


def test_stop_server_not_running(tmp_path):
    from utils.single_instance import stop_server

    arch_dir = tmp_path / ".arch"
    stopped = stop_server(arch_dir)
    assert stopped is None


def test_get_server_status(tmp_path):
    from utils.single_instance import get_server_status

    arch_dir = tmp_path / ".arch"
    # Not running
    assert get_server_status(arch_dir) is None

    # Running and healthy
    write_lock(arch_dir, 12345, 8071)
    with patch("utils.single_instance._pid_alive", return_value=True), patch(
        "utils.single_instance._server_alive", return_value=True
    ):
        status = get_server_status(arch_dir)
        assert status is not None
        assert status["pid"] == 12345
        assert status["port"] == 8071
        assert status["healthy"] is True


def test_cmd_mcp_stop(capsys, tmp_path):
    import argparse
    from commands.mcp import cmd_mcp

    args = argparse.Namespace(
        project_root=str(tmp_path),
        port=0,
        stop=True,
        restart=False,
        status=False,
        headless=False,
        foreground=False,
    )
    with patch("utils.single_instance.stop_server", return_value=1234):
        try:
            cmd_mcp(args)
        except SystemExit as e:
            assert e.code == 0
    captured = capsys.readouterr().out
    assert "Stopped server (PID 1234)" in captured


def test_cmd_mcp_status(capsys, tmp_path):
    import argparse
    from commands.mcp import cmd_mcp

    args = argparse.Namespace(
        project_root=str(tmp_path),
        port=0,
        stop=False,
        restart=False,
        status=True,
        headless=False,
        foreground=False,
    )
    mock_status = {
        "pid": 5678,
        "port": 8071,
        "url": "http://127.0.0.1:8071",
        "healthy": True,
    }
    with patch("utils.single_instance.get_server_status", return_value=mock_status):
        try:
            cmd_mcp(args)
        except SystemExit as e:
            assert e.code == 0
    captured = capsys.readouterr().out
    assert "http://127.0.0.1:8071" in captured
    assert "5678" in captured
    assert "Healthy" in captured


def test_cmd_mcp_already_running_notice(capsys, tmp_path):
    import argparse
    from commands.mcp import cmd_mcp

    args = argparse.Namespace(
        project_root=str(tmp_path),
        port=0,
        stop=False,
        restart=False,
        status=False,
        headless=False,
        foreground=False,
    )
    mock_status = {
        "pid": 5678,
        "port": 8071,
        "url": "http://127.0.0.1:8071",
        "healthy": True,
    }
    with patch("utils.single_instance.get_server_status", return_value=mock_status):
        try:
            cmd_mcp(args)
        except SystemExit as e:
            assert e.code == 0
    captured = capsys.readouterr().out
    assert "Server is already running" in captured
    assert "--stop" in captured
    assert "--restart" in captured


def test_cmd_mcp_headless_start(capsys, tmp_path):
    import argparse
    from commands.mcp import cmd_mcp

    args = argparse.Namespace(
        project_root=str(tmp_path),
        port=0,
        stop=False,
        restart=False,
        status=False,
        headless=True,
        foreground=False,
    )
    mock_info = {
        "pid": 9999,
        "port": 8071,
        "url": "http://127.0.0.1:8071",
        "healthy": True,
    }
    with patch("utils.single_instance.get_server_status", return_value=None), patch(
        "utils.single_instance.start_headless", return_value=mock_info
    ):
        try:
            cmd_mcp(args)
        except SystemExit as e:
            assert e.code == 0
    captured = capsys.readouterr().out
    assert "Server started successfully" in captured
    assert "http://127.0.0.1:8071" in captured
    assert "9999" in captured
