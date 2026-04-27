"""Tests for the bootstrap hook loader (core.bootstrap)."""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest
from core import bootstrap as bootstrap_mod
from core.bootstrap import load_bootstrap


@pytest.fixture
def bootstrap_env(tmp_path, monkeypatch):
    """Give each test a clean tmp dir on sys.path and a fresh loader state."""
    monkeypatch.syspath_prepend(str(tmp_path))
    bootstrap_mod._reset_for_tests()
    sys.modules.pop('bootstrap', None)
    yield tmp_path
    sys.modules.pop('bootstrap', None)
    bootstrap_mod._reset_for_tests()


def _write_bootstrap(tmp_path, body: str) -> None:
    (tmp_path / 'bootstrap.py').write_text(body)


def test_no_file_is_silent(bootstrap_env):
    with patch.object(bootstrap_mod, '_log') as mock_log:
        load_bootstrap()
    mock_log.warning.assert_not_called()


def test_calls_bootstrap_function(bootstrap_env):
    _write_bootstrap(bootstrap_env, ("called = {'n': 0}\ndef bootstrap():\n    called['n'] += 1\n"))
    load_bootstrap()
    import bootstrap as user_bootstrap

    assert user_bootstrap.called['n'] == 1


def test_is_idempotent(bootstrap_env):
    _write_bootstrap(bootstrap_env, ("called = {'n': 0}\ndef bootstrap():\n    called['n'] += 1\n"))
    load_bootstrap()
    load_bootstrap()
    load_bootstrap()
    import bootstrap as user_bootstrap

    assert user_bootstrap.called['n'] == 1


def test_missing_function_is_silent(bootstrap_env):
    _write_bootstrap(bootstrap_env, 'x = 42\n')
    with patch.object(bootstrap_mod, '_log') as mock_log:
        load_bootstrap()
    mock_log.warning.assert_not_called()


def test_raising_hook_logs_warning(bootstrap_env):
    _write_bootstrap(bootstrap_env, ("def bootstrap():\n    raise RuntimeError('boom')\n"))
    with patch.object(bootstrap_mod, '_log') as mock_log:
        load_bootstrap()
    mock_log.warning.assert_called_once()
    fmt, exc = mock_log.warning.call_args[0][0], mock_log.warning.call_args[0][1]
    assert 'bootstrap() raised' in fmt
    assert 'boom' in str(exc)


def test_import_error_logs_warning(bootstrap_env):
    _write_bootstrap(bootstrap_env, 'import a_package_that_does_not_exist_xyz\n')
    with patch.object(bootstrap_mod, '_log') as mock_log:
        load_bootstrap()
    mock_log.warning.assert_called_once()
    assert 'failed to import' in mock_log.warning.call_args[0][0]


def test_syntax_error_logs_warning(bootstrap_env):
    _write_bootstrap(bootstrap_env, 'def bootstrap(:\n    pass\n')
    with patch.object(bootstrap_mod, '_log') as mock_log:
        load_bootstrap()
    mock_log.warning.assert_called_once()
    assert 'failed to import' in mock_log.warning.call_args[0][0]
