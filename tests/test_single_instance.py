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
    with patch("utils.single_instance._find_open_port", return_value=8075):
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
