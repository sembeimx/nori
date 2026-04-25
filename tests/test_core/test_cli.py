"""Tests for CLI commands in core/cli.py.

The aerich-wrapping commands (migrate:*) are tested by mocking subprocess.run
and asserting the right arguments are passed — testing that we drive aerich
correctly, not testing aerich itself. The make:* generators are tested by
asserting the file content they produce.
"""
from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from core import cli


# ---------------------------------------------------------------------------
# make:* generators
# ---------------------------------------------------------------------------

@pytest.fixture
def app_dir(tmp_path, monkeypatch):
    for sub in ('modules', 'models', 'seeders'):
        (tmp_path / sub).mkdir()
    monkeypatch.setattr(cli, '_APP_DIR', str(tmp_path))
    return tmp_path


def test_make_controller_generates_file(app_dir, capsys):
    cli.make_controller('Article')

    target = app_dir / 'modules' / 'article.py'
    assert target.exists()
    content = target.read_text()
    assert 'class ArticleController:' in content
    assert 'from starlette.requests import Request' in content
    assert 'async def list(' in content
    assert 'Controller created at' in capsys.readouterr().out


def test_make_controller_refuses_to_overwrite(app_dir, capsys):
    target = app_dir / 'modules' / 'article.py'
    target.write_text('# existing user code')

    cli.make_controller('Article')

    assert target.read_text() == '# existing user code'
    assert 'already exists' in capsys.readouterr().out


def test_make_model_generates_file_with_reminder(app_dir, capsys):
    cli.make_model('User')

    target = app_dir / 'models' / 'user.py'
    assert target.exists()
    content = target.read_text()
    assert 'class User(NoriModelMixin, Model):' in content
    assert "table = 'user'" in content
    out = capsys.readouterr().out
    assert 'Model User created' in out
    assert 'register' in out  # reminder to wire it up in models/__init__.py


def test_make_seeder_generates_file(app_dir, capsys):
    cli.make_seeder('User')

    target = app_dir / 'seeders' / 'user_seeder.py'
    assert target.exists()
    content = target.read_text()
    assert 'async def run() -> None:' in content
    assert 'Seeder for User' in content
    assert 'Seeder created at' in capsys.readouterr().out


# ---------------------------------------------------------------------------
# migrate:init
# ---------------------------------------------------------------------------

@pytest.fixture
def migrations_env(tmp_path, monkeypatch):
    (tmp_path / 'migrations').mkdir()
    monkeypatch.setattr(cli, '_APP_DIR', str(tmp_path))
    return tmp_path


def _aerich_arg(call, flag: str) -> str | None:
    args = call.args[0]
    if flag not in args:
        return None
    return args[args.index(flag) + 1]


def test_migrate_init_runs_init_then_init_db_per_app(migrations_env):
    with patch('subprocess.run') as mock_run:
        cli.migrate_init()

    calls = mock_run.call_args_list
    # First call: `aerich init -t settings.TORTOISE_ORM`
    first_args = calls[0].args[0]
    assert 'aerich' in first_args
    assert 'init' in first_args
    assert _aerich_arg(calls[0], '-t') == 'settings.TORTOISE_ORM'

    # Subsequent calls: `aerich --app <name> init-db` for both apps in order
    init_db_calls = [c for c in calls[1:] if 'init-db' in c.args[0]]
    apps = [_aerich_arg(c, '--app') for c in init_db_calls]
    assert apps == ['framework', 'models']


def test_migrate_init_skips_apps_with_existing_migrations(migrations_env, capsys):
    fw_dir = migrations_env / 'migrations' / 'framework'
    fw_dir.mkdir()
    (fw_dir / '0_init.py').write_text('# pre-existing')

    with patch('subprocess.run') as mock_run:
        cli.migrate_init()

    init_db_calls = [c for c in mock_run.call_args_list if 'init-db' in c.args[0]]
    apps = [_aerich_arg(c, '--app') for c in init_db_calls]
    assert apps == ['models']
    assert "App 'framework' already initialized" in capsys.readouterr().out


def test_migrate_init_ignores_init_py_for_idempotence_check(migrations_env):
    """A bare __init__.py in migrations/<app>/ should NOT count as initialized."""
    fw_dir = migrations_env / 'migrations' / 'framework'
    fw_dir.mkdir()
    (fw_dir / '__init__.py').write_text('')

    with patch('subprocess.run') as mock_run:
        cli.migrate_init()

    init_db_calls = [c for c in mock_run.call_args_list if 'init-db' in c.args[0]]
    apps = [_aerich_arg(c, '--app') for c in init_db_calls]
    assert apps == ['framework', 'models']  # both run


# ---------------------------------------------------------------------------
# migrate:make / migrate:upgrade / migrate:downgrade
# ---------------------------------------------------------------------------

def test_migrate_make_defaults_to_models_app():
    with patch('subprocess.run') as mock_run:
        cli.migrate_make('add_email_to_users')

    call = mock_run.call_args_list[0]
    assert _aerich_arg(call, '--app') == 'models'
    assert _aerich_arg(call, '--name') == 'add_email_to_users'
    assert 'migrate' in call.args[0]


def test_migrate_make_supports_framework_app():
    with patch('subprocess.run') as mock_run:
        cli.migrate_make('add_audit_index', app='framework')

    call = mock_run.call_args_list[0]
    assert _aerich_arg(call, '--app') == 'framework'


def test_migrate_upgrade_without_app_runs_both_in_order():
    with patch('subprocess.run') as mock_run:
        cli.migrate_upgrade()

    apps = [_aerich_arg(c, '--app') for c in mock_run.call_args_list]
    assert apps == ['framework', 'models']
    assert all('upgrade' in c.args[0] for c in mock_run.call_args_list)


def test_migrate_upgrade_with_explicit_app_runs_only_that_one():
    with patch('subprocess.run') as mock_run:
        cli.migrate_upgrade(app='framework')

    apps = [_aerich_arg(c, '--app') for c in mock_run.call_args_list]
    assert apps == ['framework']


def test_migrate_downgrade_passes_steps_and_delete_flags():
    with patch('subprocess.run') as mock_run:
        cli.migrate_downgrade(steps=3, delete=True, app='models')

    args = mock_run.call_args_list[0].args[0]
    assert _aerich_arg(mock_run.call_args_list[0], '--app') == 'models'
    assert _aerich_arg(mock_run.call_args_list[0], '-v') == '3'
    assert '-d' in args


def test_migrate_downgrade_omits_delete_flag_by_default():
    with patch('subprocess.run') as mock_run:
        cli.migrate_downgrade(steps=1, delete=False, app='models')

    args = mock_run.call_args_list[0].args[0]
    assert '-d' not in args


# ---------------------------------------------------------------------------
# migrate:fresh — DEBUG-only safety check
# ---------------------------------------------------------------------------

def test_migrate_fresh_refuses_when_debug_is_false(monkeypatch, capsys):
    monkeypatch.setattr(
        'subprocess.check_output',
        lambda *a, **kw: b'DEBUG_FALSE',
    )
    cli.migrate_fresh()

    out = capsys.readouterr().out
    assert 'can only be run when DEBUG=true' in out


def test_migrate_fresh_aborts_if_user_does_not_confirm(monkeypatch, capsys):
    monkeypatch.setattr(
        'subprocess.check_output',
        lambda *a, **kw: b'DEBUG_TRUE',
    )
    monkeypatch.setattr('builtins.input', lambda _: 'no')

    cli.migrate_fresh()

    out = capsys.readouterr().out
    assert 'Aborted' in out


# ---------------------------------------------------------------------------
# framework:version
# ---------------------------------------------------------------------------

def test_framework_version_prints_current_version(capsys):
    cli.framework_version()
    out = capsys.readouterr().out.strip()
    assert out.startswith('Nori v')
    assert len(out) > len('Nori v')  # has a version after the prefix
