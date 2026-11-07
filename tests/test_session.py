import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
from utils.session import get_project_root, workspace_session, db_session


class TestGetProjectRoot:
    def test_env_var_takes_priority_when_args_is_dot(self):
        args = MagicMock()
        args.project_root = "."
        with patch.dict(os.environ, {"ARCH_PROJECT_ROOT": "/from/env"}):
            result = get_project_root(args)
            assert result == Path("/from/env").resolve()

    def test_args_used_when_no_env(self):
        args = MagicMock()
        args.project_root = "/from/args"
        with patch.dict(os.environ, {}, clear=True):
            result = get_project_root(args)
            assert result == Path("/from/args").resolve()

    def test_env_skipped_when_args_not_dot(self):
        args = MagicMock()
        args.project_root = "/from/args"
        with patch.dict(os.environ, {"ARCH_PROJECT_ROOT": "/from/env"}):
            result = get_project_root(args)
            assert result == Path("/from/args").resolve()

    def test_env_used_when_no_args(self):
        with patch.dict(os.environ, {"ARCH_PROJECT_ROOT": "/from/env"}):
            result = get_project_root(None)
            assert result == Path("/from/env").resolve()

    def test_fallback_to_cwd(self):
        args = MagicMock()
        args.project_root = "."
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(sys, "argv", ["arch", "init"]):
            result = get_project_root(args)
            assert result == Path.cwd().resolve()

    def test_no_args_uses_argv(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(sys, "argv", ["arch", "audit", "/custom/path"]):
            result = get_project_root(None)
            assert result == Path("/custom/path").resolve()

    def test_argv_flag_args_skipped(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(sys, "argv", ["arch", "--verbose", "/real/path"]):
            result = get_project_root(None)
            assert result == Path("/real/path").resolve()

    def test_no_args_falls_to_cwd(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(sys, "argv", ["arch"]):
            result = get_project_root(None)
            assert result == Path.cwd().resolve()


class TestWorkspaceSession:
    def test_exits_when_arch_dir_missing(self, tmp_path):
        args = MagicMock()
        args.project_root = str(tmp_path)
        with patch("utils.session.get_project_root", return_value=tmp_path), \
             patch("sys.exit") as mock_exit:
            try:
                with workspace_session(args):
                    pass
            except SystemExit:
                pass
            mock_exit.assert_called_once_with(1)

    def test_yields_correct_values(self, tmp_path):
        arch_dir = tmp_path / ".arch"
        arch_dir.mkdir()
        args = MagicMock()
        args.project_root = str(tmp_path)
        with patch("utils.session.get_project_root", return_value=tmp_path), \
             patch("utils.session.DbConnection") as mock_db, \
             patch("utils.session.Repository") as mock_repo:
            mock_db.return_value.close = MagicMock()
            with workspace_session(args) as (root, arch, repo):
                assert root == tmp_path
                assert arch == arch_dir

    def test_closes_db_conn_in_finally(self, tmp_path):
        arch_dir = tmp_path / ".arch"
        arch_dir.mkdir()
        args = MagicMock()
        args.project_root = str(tmp_path)
        mock_conn = MagicMock()
        with patch("utils.session.get_project_root", return_value=tmp_path), \
             patch("utils.session.DbConnection", return_value=mock_conn), \
             patch("utils.session.Repository"):
            with workspace_session(args):
                pass
            mock_conn.close.assert_called_once()


class TestDbSession:
    def test_raises_when_db_missing(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            with db_session(tmp_path):
                pass

    def test_yields_repository_and_conn(self, tmp_path):
        arch_dir = tmp_path / ".arch"
        arch_dir.mkdir()
        db_path = arch_dir / "arch.db"
        db_path.touch()
        with patch("utils.session.DbConnection") as mock_db, \
             patch("utils.session.Repository") as mock_repo:
            mock_db.return_value.close = MagicMock()
            with db_session(tmp_path) as (repo, conn):
                assert repo is mock_repo.return_value

    def test_closes_conn_in_finally(self, tmp_path):
        arch_dir = tmp_path / ".arch"
        arch_dir.mkdir()
        db_path = arch_dir / "arch.db"
        db_path.touch()
        mock_conn = MagicMock()
        with patch("utils.session.DbConnection", return_value=mock_conn), \
             patch("utils.session.Repository"):
            with db_session(tmp_path):
                pass
            mock_conn.close.assert_called_once()


import pytest
