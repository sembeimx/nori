"""Tests for the post-update patch system (core.cli._apply_patches)."""
from __future__ import annotations

import pytest

from core import cli


ASGI_WITH_FUTURE_AND_DOCSTRING = '''\
from __future__ import annotations

"""
Nori - ASGI Entry Point
Start with: uvicorn asgi:app --reload --host 0.0.0.0 --port 8000
"""
from contextlib import asynccontextmanager

from starlette.applications import Starlette
'''

ASGI_WITHOUT_DOCSTRING = '''\
from __future__ import annotations

from starlette.applications import Starlette
'''

ASGI_BARE = '''\
from starlette.applications import Starlette
'''

ASGI_ALREADY_PATCHED = '''\
from __future__ import annotations

"""Docstring."""

from core.bootstrap import load_bootstrap
load_bootstrap()

from starlette.applications import Starlette
'''


@pytest.fixture
def asgi_file(tmp_path, monkeypatch):
    """Redirect _ASGI_FILE to a temp file for the duration of the test."""
    target = tmp_path / 'asgi.py'
    monkeypatch.setattr(cli, '_ASGI_FILE', str(target))
    return target


def test_patch_injects_after_docstring_and_future(asgi_file):
    asgi_file.write_text(ASGI_WITH_FUTURE_AND_DOCSTRING)

    changed = cli._patch_bootstrap_hook_in_asgi()

    assert changed is True
    result = asgi_file.read_text()
    assert 'from core.bootstrap import load_bootstrap' in result
    assert 'load_bootstrap()' in result
    # Must appear BEFORE any starlette import
    assert result.index('load_bootstrap()') < result.index('from starlette')
    # Must appear AFTER the docstring (which ends with its closing """)
    assert result.index('"""\n', result.index('Nori - ASGI')) < result.index('load_bootstrap()')


def test_patch_is_idempotent(asgi_file):
    asgi_file.write_text(ASGI_ALREADY_PATCHED)
    before = asgi_file.read_text()

    changed = cli._patch_bootstrap_hook_in_asgi()

    assert changed is False
    assert asgi_file.read_text() == before


def test_patch_without_docstring(asgi_file):
    asgi_file.write_text(ASGI_WITHOUT_DOCSTRING)

    changed = cli._patch_bootstrap_hook_in_asgi()

    assert changed is True
    result = asgi_file.read_text()
    assert result.index('from __future__') < result.index('load_bootstrap()')
    assert result.index('load_bootstrap()') < result.index('from starlette')


def test_patch_bare_file(asgi_file):
    asgi_file.write_text(ASGI_BARE)

    changed = cli._patch_bootstrap_hook_in_asgi()

    assert changed is True
    result = asgi_file.read_text()
    assert result.index('load_bootstrap()') < result.index('from starlette')


def test_patch_missing_file(asgi_file):
    # asgi_file.write_text never called — file does not exist
    assert cli._patch_bootstrap_hook_in_asgi() is False


def test_patch_syntax_error_file(asgi_file, capsys):
    asgi_file.write_text('def broken(:\n    pass\n')

    changed = cli._patch_bootstrap_hook_in_asgi()

    assert changed is False
    captured = capsys.readouterr()
    assert 'cannot parse asgi.py' in captured.out


def test_apply_patches_reports_applied(asgi_file):
    asgi_file.write_text(ASGI_WITH_FUTURE_AND_DOCSTRING)

    applied = cli._apply_patches()

    assert applied == ['asgi.py: added bootstrap hook']


def test_apply_patches_empty_when_nothing_to_do(asgi_file):
    asgi_file.write_text(ASGI_ALREADY_PATCHED)

    applied = cli._apply_patches()

    assert applied == []


def test_patched_file_is_valid_python(asgi_file):
    """Injected code must not break AST parsing of the result."""
    import ast
    asgi_file.write_text(ASGI_WITH_FUTURE_AND_DOCSTRING)

    cli._patch_bootstrap_hook_in_asgi()

    ast.parse(asgi_file.read_text())
