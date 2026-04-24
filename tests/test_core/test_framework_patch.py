"""Tests for the post-update patch system (core._patches)."""
from __future__ import annotations

import pytest

from core import _patches


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

REQUIREMENTS_V15 = '''\
starlette>=0.28
uvicorn[standard]>=0.29
tortoise-orm>=0.25
# redis[hiredis]
'''

REQUIREMENTS_ALREADY_PATCHED = '''\
-r requirements.nori.txt

starlette>=0.28
'''

REQUIREMENTS_WITH_LEADING_COMMENT = '''\
# Site deps — updated 2026-04-01
starlette>=0.28
'''


@pytest.fixture
def patch_env(tmp_path, monkeypatch):
    """Redirect both patch targets into tmp_path so tests are hermetic."""
    asgi = tmp_path / 'asgi.py'
    requirements = tmp_path / 'requirements.txt'
    monkeypatch.setattr(_patches, '_ASGI_FILE', str(asgi))
    monkeypatch.setattr(_patches, '_REQUIREMENTS_FILE', str(requirements))
    return {'asgi': asgi, 'requirements': requirements}


# ---------------------------------------------------------------------------
# bootstrap-hook patcher
# ---------------------------------------------------------------------------

def test_bootstrap_patch_injects_after_docstring_and_future(patch_env):
    patch_env['asgi'].write_text(ASGI_WITH_FUTURE_AND_DOCSTRING)

    changed = _patches._patch_bootstrap_hook_in_asgi()

    assert changed is True
    result = patch_env['asgi'].read_text()
    assert 'from core.bootstrap import load_bootstrap' in result
    assert 'load_bootstrap()' in result
    assert result.index('load_bootstrap()') < result.index('from starlette')
    assert result.index('"""\n', result.index('Nori - ASGI')) < result.index('load_bootstrap()')


def test_bootstrap_patch_is_idempotent(patch_env):
    patch_env['asgi'].write_text(ASGI_ALREADY_PATCHED)
    before = patch_env['asgi'].read_text()

    changed = _patches._patch_bootstrap_hook_in_asgi()

    assert changed is False
    assert patch_env['asgi'].read_text() == before


def test_bootstrap_patch_without_docstring(patch_env):
    patch_env['asgi'].write_text(ASGI_WITHOUT_DOCSTRING)

    changed = _patches._patch_bootstrap_hook_in_asgi()

    assert changed is True
    result = patch_env['asgi'].read_text()
    assert result.index('from __future__') < result.index('load_bootstrap()')
    assert result.index('load_bootstrap()') < result.index('from starlette')


def test_bootstrap_patch_bare_file(patch_env):
    patch_env['asgi'].write_text(ASGI_BARE)

    changed = _patches._patch_bootstrap_hook_in_asgi()

    assert changed is True
    result = patch_env['asgi'].read_text()
    assert result.index('load_bootstrap()') < result.index('from starlette')


def test_bootstrap_patch_missing_file(patch_env):
    assert _patches._patch_bootstrap_hook_in_asgi() is False


def test_bootstrap_patch_syntax_error_file(patch_env, capsys):
    patch_env['asgi'].write_text('def broken(:\n    pass\n')

    changed = _patches._patch_bootstrap_hook_in_asgi()

    assert changed is False
    captured = capsys.readouterr()
    assert 'cannot parse asgi.py' in captured.out


def test_bootstrap_patched_file_is_valid_python(patch_env):
    import ast
    patch_env['asgi'].write_text(ASGI_WITH_FUTURE_AND_DOCSTRING)

    _patches._patch_bootstrap_hook_in_asgi()

    ast.parse(patch_env['asgi'].read_text())


# ---------------------------------------------------------------------------
# requirements.nori.txt patcher
# ---------------------------------------------------------------------------

def test_requirements_patch_injects_dash_r_at_top(patch_env):
    patch_env['requirements'].write_text(REQUIREMENTS_V15)

    changed = _patches._patch_requirements_dash_r_to_nori()

    assert changed is True
    result = patch_env['requirements'].read_text()
    assert result.startswith('-r requirements.nori.txt\n')
    assert 'starlette>=0.28' in result  # original deps preserved


def test_requirements_patch_is_idempotent(patch_env):
    patch_env['requirements'].write_text(REQUIREMENTS_ALREADY_PATCHED)
    before = patch_env['requirements'].read_text()

    changed = _patches._patch_requirements_dash_r_to_nori()

    assert changed is False
    assert patch_env['requirements'].read_text() == before


def test_requirements_patch_preserves_leading_comments(patch_env):
    patch_env['requirements'].write_text(REQUIREMENTS_WITH_LEADING_COMMENT)

    changed = _patches._patch_requirements_dash_r_to_nori()

    assert changed is True
    result = patch_env['requirements'].read_text()
    assert result.startswith('-r requirements.nori.txt\n')
    assert '# Site deps — updated 2026-04-01' in result


def test_requirements_patch_missing_file(patch_env):
    assert _patches._patch_requirements_dash_r_to_nori() is False


# ---------------------------------------------------------------------------
# apply() — runs all patchers
# ---------------------------------------------------------------------------

def test_apply_runs_both_patchers(patch_env):
    patch_env['asgi'].write_text(ASGI_WITH_FUTURE_AND_DOCSTRING)
    patch_env['requirements'].write_text(REQUIREMENTS_V15)

    applied = _patches.apply()

    assert 'asgi.py: added bootstrap hook' in applied
    assert 'requirements.txt: added -r requirements.nori.txt' in applied
    assert len(applied) == 2


def test_apply_reports_only_asgi_when_requirements_missing(patch_env):
    patch_env['asgi'].write_text(ASGI_WITH_FUTURE_AND_DOCSTRING)

    applied = _patches.apply()

    assert applied == ['asgi.py: added bootstrap hook']


def test_apply_reports_only_requirements_when_asgi_missing(patch_env):
    patch_env['requirements'].write_text(REQUIREMENTS_V15)

    applied = _patches.apply()

    assert applied == ['requirements.txt: added -r requirements.nori.txt']


def test_apply_empty_when_nothing_to_do(patch_env):
    patch_env['asgi'].write_text(ASGI_ALREADY_PATCHED)
    patch_env['requirements'].write_text(REQUIREMENTS_ALREADY_PATCHED)

    applied = _patches.apply()

    assert applied == []


def test_apply_continues_after_individual_patcher_failure(patch_env, monkeypatch, capsys):
    """If one patcher raises, others still run and a warning is printed."""
    patch_env['requirements'].write_text(REQUIREMENTS_V15)

    def broken_patcher():
        raise RuntimeError('boom')

    # Swap the first entry in _PATCHERS so it raises; the second still fires.
    original = list(_patches._PATCHERS)
    monkeypatch.setattr(_patches, '_PATCHERS', [
        (broken_patcher, 'fake patch'),
        original[1],
    ])

    applied = _patches.apply()

    assert applied == ['requirements.txt: added -r requirements.nori.txt']
    captured = capsys.readouterr()
    assert 'fake patch' in captured.out
    assert 'boom' in captured.out
