"""Tests for the CLI plugin system (_load_user_commands)."""
from __future__ import annotations

import argparse
import os
import tempfile
import sys
import pytest

from core.cli import _load_user_commands


@pytest.fixture
def commands_dir(tmp_path, monkeypatch):
    """Create a temporary commands/ directory and chdir into tmp_path."""
    cmd_dir = tmp_path / 'commands'
    cmd_dir.mkdir()
    (cmd_dir / '__init__.py').touch()
    monkeypatch.chdir(tmp_path)
    # Ensure tmp_path is on sys.path so imports work
    sys.path.insert(0, str(tmp_path))
    yield cmd_dir
    sys.path.remove(str(tmp_path))
    # Clean up imported command modules from sys.modules
    to_remove = [k for k in sys.modules if k == 'commands' or k.startswith('commands.')]
    for k in to_remove:
        del sys.modules[k]


def _make_parser():
    parser = argparse.ArgumentParser()
    return parser.add_subparsers(dest='command')


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_no_commands_dir(tmp_path, monkeypatch):
    """Returns empty dict when commands/ does not exist."""
    monkeypatch.chdir(tmp_path)
    subparsers = _make_parser()
    handlers = _load_user_commands(subparsers)
    assert handlers == {}


def test_empty_commands_dir(commands_dir):
    """Returns empty dict when commands/ exists but has no .py files."""
    subparsers = _make_parser()
    handlers = _load_user_commands(subparsers)
    assert handlers == {}


def test_underscore_prefix_skipped(commands_dir):
    """Files starting with _ are skipped."""
    (commands_dir / '_example.py').write_text(
        "def register(s): s.add_parser('skip')\n"
        "def handle(a): pass\n"
    )
    subparsers = _make_parser()
    handlers = _load_user_commands(subparsers)
    assert 'skip' not in handlers


def test_valid_plugin_loaded(commands_dir):
    """A valid plugin with register() and handle() is loaded correctly."""
    (commands_dir / 'greet.py').write_text(
        "def register(subparsers):\n"
        "    subparsers.add_parser('app:greet', help='Say hi')\n"
        "\n"
        "def handle(args):\n"
        "    print('Hello!')\n"
    )
    subparsers = _make_parser()
    handlers = _load_user_commands(subparsers)
    assert 'app:greet' in handlers
    assert callable(handlers['app:greet'])


def test_multiple_plugins_loaded(commands_dir):
    """Multiple plugin files are all loaded."""
    (commands_dir / 'alpha.py').write_text(
        "def register(s): s.add_parser('alpha')\n"
        "def handle(a): pass\n"
    )
    (commands_dir / 'beta.py').write_text(
        "def register(s): s.add_parser('beta')\n"
        "def handle(a): pass\n"
    )
    subparsers = _make_parser()
    handlers = _load_user_commands(subparsers)
    assert 'alpha' in handlers
    assert 'beta' in handlers


def test_missing_register_skipped(commands_dir, capsys):
    """Plugin without register() is skipped with a warning."""
    (commands_dir / 'bad.py').write_text(
        "def handle(a): pass\n"
    )
    subparsers = _make_parser()
    handlers = _load_user_commands(subparsers)
    assert handlers == {}
    captured = capsys.readouterr()
    assert 'missing register() or handle()' in captured.out


def test_missing_handle_skipped(commands_dir, capsys):
    """Plugin without handle() is skipped with a warning."""
    (commands_dir / 'nohandle.py').write_text(
        "def register(s): s.add_parser('nohandle')\n"
    )
    subparsers = _make_parser()
    handlers = _load_user_commands(subparsers)
    assert handlers == {}
    captured = capsys.readouterr()
    assert 'missing register() or handle()' in captured.out


def test_import_error_skipped(commands_dir, capsys):
    """Plugin with import error is skipped with a warning."""
    (commands_dir / 'broken.py').write_text(
        "import nonexistent_module_xyz\n"
        "def register(s): pass\n"
        "def handle(a): pass\n"
    )
    subparsers = _make_parser()
    handlers = _load_user_commands(subparsers)
    assert handlers == {}
    captured = capsys.readouterr()
    assert 'failed to load' in captured.out


def test_register_error_skipped(commands_dir, capsys):
    """Plugin whose register() raises is skipped with a warning."""
    (commands_dir / 'crashy.py').write_text(
        "def register(s): raise RuntimeError('boom')\n"
        "def handle(a): pass\n"
    )
    subparsers = _make_parser()
    handlers = _load_user_commands(subparsers)
    assert handlers == {}
    captured = capsys.readouterr()
    assert 'register()' in captured.out and 'failed' in captured.out


def test_plugin_with_arguments(commands_dir):
    """Plugin can register subparser with arguments."""
    (commands_dir / 'withargs.py').write_text(
        "def register(s):\n"
        "    p = s.add_parser('app:deploy')\n"
        "    p.add_argument('--env', default='staging')\n"
        "\n"
        "def handle(args):\n"
        "    print(f'Deploying to {args.env}')\n"
    )
    subparsers = _make_parser()
    handlers = _load_user_commands(subparsers)
    assert 'app:deploy' in handlers


def test_init_py_skipped(commands_dir):
    """__init__.py is not loaded as a plugin."""
    (commands_dir / '__init__.py').write_text(
        "def register(s): s.add_parser('init')\n"
        "def handle(a): pass\n"
    )
    subparsers = _make_parser()
    handlers = _load_user_commands(subparsers)
    assert 'init' not in handlers
