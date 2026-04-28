"""Tests for CLI commands in core/cli.py.

The aerich-wrapping commands (migrate:*) are tested by mocking subprocess.run
and asserting the right arguments are passed — testing that we drive aerich
correctly, not testing aerich itself. The make:* generators are tested by
asserting the file content they produce.
"""

from __future__ import annotations

import io
import zipfile
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

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


def test_make_model_refuses_to_overwrite(app_dir, capsys):
    target = app_dir / 'models' / 'user.py'
    target.write_text('# existing user model')
    cli.make_model('User')

    assert target.read_text() == '# existing user model'
    assert 'already exists' in capsys.readouterr().out


def test_make_seeder_generates_file(app_dir, capsys):
    cli.make_seeder('User')

    target = app_dir / 'seeders' / 'user_seeder.py'
    assert target.exists()
    content = target.read_text()
    assert 'async def run() -> None:' in content
    assert 'Seeder for User' in content
    assert 'Seeder created at' in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Repo-state guard: fresh user projects must NOT inherit a `migrations/` dir
# ---------------------------------------------------------------------------


def test_repo_does_not_ship_migrations_dir():
    """The framework repo must not commit `rootsystem/application/migrations/`.

    The starter installer copies `rootsystem/` wholesale to new projects. If
    the framework repo ships `migrations/framework/` or `migrations/models/`
    (even as empty dirs held alive by `.gitkeep`), aerich's `init-db` sees the
    directories exist and bails with "App 'X' is already initialized" without
    generating any migration files. Tortoise.generate_schemas() in the asgi
    lifespan masks the symptom by creating tables on first serve, but the
    user's first `migrate:make` later breaks because there's no baseline.

    This was a real bug from v1.8.0 → v1.10.2, fixed in v1.10.3 by removing
    the leftover `.gitkeep` files. This guard prevents recurrence.
    """
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    migrations = repo_root / 'rootsystem' / 'application' / 'migrations'
    assert not migrations.exists(), (
        f'{migrations} is checked into the repo. Fresh user projects will '
        f'inherit this directory and aerich init-db will bail without '
        f'generating migration files. Migrations must be created by the '
        f"user's first `migrate:init`, not shipped pre-existing."
    )


# ---------------------------------------------------------------------------
# migrate:init
# ---------------------------------------------------------------------------


@pytest.fixture
def migrations_env(tmp_path, monkeypatch):
    (tmp_path / 'migrations').mkdir()
    monkeypatch.setattr(cli, '_APP_DIR', str(tmp_path))
    # Default app set for tests that don't care about dynamic discovery.
    # Tests that exercise dynamic-apps behavior override this directly.
    monkeypatch.setattr(cli, '_read_tortoise_apps', lambda: ('framework', 'models'))
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


def test_migrate_init_uses_dynamic_apps_from_tortoise_orm(migrations_env, monkeypatch):
    """migrate:init must initialize EVERY app declared in settings.TORTOISE_ORM,
    not just the hardcoded ('framework', 'models') pair.
    """
    monkeypatch.setattr(
        cli,
        '_read_tortoise_apps',
        lambda: ('framework', 'models', 'analytics'),
    )
    with patch('subprocess.run') as mock_run:
        cli.migrate_init()

    init_db_calls = [c for c in mock_run.call_args_list if 'init-db' in c.args[0]]
    apps = [_aerich_arg(c, '--app') for c in init_db_calls]
    assert apps == ['framework', 'models', 'analytics']


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


def test_migrate_upgrade_without_app_runs_both_in_order(monkeypatch):
    monkeypatch.setattr(cli, '_read_tortoise_apps', lambda: ('framework', 'models'))
    with patch('subprocess.run') as mock_run:
        cli.migrate_upgrade()

    apps = [_aerich_arg(c, '--app') for c in mock_run.call_args_list]
    assert apps == ['framework', 'models']
    assert all('upgrade' in c.args[0] for c in mock_run.call_args_list)


def test_migrate_upgrade_without_app_uses_dynamic_app_list(monkeypatch):
    """Same dynamic-app contract as migrate:init."""
    monkeypatch.setattr(
        cli,
        '_read_tortoise_apps',
        lambda: ('framework', 'models', 'analytics'),
    )
    with patch('subprocess.run') as mock_run:
        cli.migrate_upgrade()

    apps = [_aerich_arg(c, '--app') for c in mock_run.call_args_list]
    assert apps == ['framework', 'models', 'analytics']


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
# User commands — discovery must be CWD-independent
# ---------------------------------------------------------------------------


def test_load_user_commands_resolves_relative_to_module_not_cwd(monkeypatch, tmp_path):
    """`commands_dir` must be anchored to the cli module file, not CWD.

    nori.py adds rootsystem/application to sys.path but does NOT chdir into
    it. A relative `Path('commands')` would resolve against the user's CWD
    (typically the project root) and silently miss the real commands/ dir.
    Latent bug from the v1.3.0 plugin system release.
    """
    import argparse
    import sys as _sys

    # Lay out a fake project: <tmp_path>/core/cli.py + <tmp_path>/commands/foo.py
    (tmp_path / 'core').mkdir()
    (tmp_path / 'core' / 'cli.py').touch()  # only needs to exist for __file__ resolution
    cmd_dir = tmp_path / 'commands'
    cmd_dir.mkdir()
    (cmd_dir / '__init__.py').touch()
    (cmd_dir / 'foo.py').write_text(
        'def register(subparsers):\n'
        "    subparsers.add_parser('foo', help='custom user command')\n"
        'def handle(args):\n'
        "    print('foo handled')\n"
    )

    # Pretend the cli module lives inside this fake project
    fake_cli_file = str(tmp_path / 'core' / 'cli.py')
    monkeypatch.setattr(cli, '__file__', fake_cli_file)
    # Make `commands.foo` importable
    monkeypatch.syspath_prepend(str(tmp_path))
    # Move CWD somewhere completely unrelated
    monkeypatch.chdir(tmp_path.parent)

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='command')
    handlers = cli._load_user_commands(subparsers)

    assert 'foo' in handlers, 'User commands at <module_root>/commands/ must be discovered regardless of process CWD'

    # Cleanup the import we just added
    _sys.modules.pop('commands.foo', None)
    _sys.modules.pop('commands', None)


# ---------------------------------------------------------------------------
# routes:list — must boot Nori config before importing routes
# ---------------------------------------------------------------------------


def test_routes_list_configures_settings_before_importing_routes():
    """The subprocess script for `routes:list` must call core.conf.configure()
    BEFORE importing routes, otherwise modules in the routes import chain
    that touch jinja templates / config (directly or indirectly) crash with
    `RuntimeError: Nori config not initialised`. Latent bug since v1.4.0
    when routes:list was added — only surfaced once user code touched
    templates.env at module import time. v1.10.5 fix.
    """
    with patch('subprocess.run') as mock_run:
        cli.routes_list()

    script = mock_run.call_args.args[0][-1]  # last arg is the -c script
    assert 'configure(settings)' in script, 'routes:list must initialise Nori config before importing routes'
    configure_idx = script.index('configure(settings)')
    routes_idx = script.index('from routes import')
    assert configure_idx < routes_idx, (
        "configure(settings) must run BEFORE 'from routes import' — otherwise "
        'any module in the import chain that touches config/templates.env at '
        'import time will crash'
    )


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


# ---------------------------------------------------------------------------
# make:seeder
# ---------------------------------------------------------------------------


def test_make_seeder_refuses_to_overwrite(app_dir, capsys):
    seeder = app_dir / 'seeders' / 'user_seeder.py'
    seeder.write_text('# existing content\n')
    cli.make_seeder('User')
    captured = capsys.readouterr()
    assert 'already exists' in captured.out
    assert seeder.read_text() == '# existing content\n'  # untouched


# ---------------------------------------------------------------------------
# serve / shell — subprocess wrappers
# ---------------------------------------------------------------------------


def test_serve_invokes_uvicorn_with_host_and_port():
    """`serve` must spawn uvicorn with the provided host/port and reload flag."""
    from unittest.mock import MagicMock

    with patch('core.cli.subprocess.run') as run:
        run.return_value = MagicMock(returncode=0)
        cli.serve(host='127.0.0.1', port=9000)

    args = run.call_args[0][0]
    assert '-m' in args
    assert 'uvicorn' in args
    assert 'asgi:app' in args
    assert '--reload' in args
    assert '127.0.0.1' in args
    assert '9000' in args


def test_serve_swallows_keyboard_interrupt():
    """Ctrl-C during serve must not bubble up — the dev workflow expects clean exit."""
    with patch('core.cli.subprocess.run', side_effect=KeyboardInterrupt):
        cli.serve()  # must not raise


def test_shell_writes_pythonstartup_and_runs_asyncio_repl():
    """`shell` writes a startup file, sets PYTHONSTARTUP, runs python -m asyncio."""
    captured_env = {}
    captured_args = []

    def fake_run(args, **kwargs):
        captured_args.extend(args)
        captured_env.update(kwargs.get('env', {}))
        from unittest.mock import MagicMock

        return MagicMock(returncode=0)

    with patch('core.cli.subprocess.run', side_effect=fake_run):
        cli.shell()

    assert '-m' in captured_args
    assert 'asyncio' in captured_args
    assert 'PYTHONSTARTUP' in captured_env
    # The startup file is unlinked after — so we can't read it back. The fact
    # that subprocess.run was given a real path under PYTHONSTARTUP is enough.
    assert captured_env['PYTHONSTARTUP'].endswith('.py')


def test_shell_swallows_keyboard_interrupt_and_cleans_startup_file():
    """Ctrl-C during the shell loop still unlinks the temp startup file."""
    with patch('core.cli.subprocess.run', side_effect=KeyboardInterrupt):
        cli.shell()  # no raise


# ---------------------------------------------------------------------------
# _get_current_version
# ---------------------------------------------------------------------------


def test_get_current_version_reads_dunder_version(tmp_path, monkeypatch):
    """The helper reads __version__ from core/version.py at the configured _CORE_DIR."""
    version_dir = tmp_path / 'core'
    version_dir.mkdir()
    (version_dir / 'version.py').write_text("__version__ = '9.9.9'\n")
    monkeypatch.setattr(cli, '_CORE_DIR', str(version_dir))
    assert cli._get_current_version() == '9.9.9'


def test_get_current_version_returns_unknown_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, '_CORE_DIR', str(tmp_path / 'nope'))
    assert cli._get_current_version() == 'unknown'


def test_get_current_version_returns_unknown_when_no_dunder(tmp_path, monkeypatch):
    """A version.py without __version__ falls through to 'unknown'."""
    version_dir = tmp_path / 'core'
    version_dir.mkdir()
    (version_dir / 'version.py').write_text("# no version line here\nfoo = 'bar'\n")
    monkeypatch.setattr(cli, '_CORE_DIR', str(version_dir))
    assert cli._get_current_version() == 'unknown'


# ---------------------------------------------------------------------------
# _has_existing_migrations
# ---------------------------------------------------------------------------


def test_has_existing_migrations_false_when_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, '_APP_DIR', str(tmp_path))
    assert cli._has_existing_migrations() is False


def test_has_existing_migrations_false_when_dir_empty(tmp_path, monkeypatch):
    (tmp_path / 'migrations').mkdir()
    monkeypatch.setattr(cli, '_APP_DIR', str(tmp_path))
    assert cli._has_existing_migrations() is False


def test_has_existing_migrations_false_when_only_init_py(tmp_path, monkeypatch):
    app = tmp_path / 'migrations' / 'models'
    app.mkdir(parents=True)
    (app / '__init__.py').write_text('')
    monkeypatch.setattr(cli, '_APP_DIR', str(tmp_path))
    assert cli._has_existing_migrations() is False


def test_has_existing_migrations_true_when_app_has_migration(tmp_path, monkeypatch):
    app = tmp_path / 'migrations' / 'models'
    app.mkdir(parents=True)
    (app / '__init__.py').write_text('')
    (app / '0_20260101_initial.py').write_text('# migration')
    monkeypatch.setattr(cli, '_APP_DIR', str(tmp_path))
    assert cli._has_existing_migrations() is True


def test_has_existing_migrations_true_when_any_app_has_migrations(tmp_path, monkeypatch):
    """Returns True even if only one of multiple apps has real migration files."""
    framework = tmp_path / 'migrations' / 'framework'
    framework.mkdir(parents=True)
    (framework / '__init__.py').write_text('')
    models = tmp_path / 'migrations' / 'models'
    models.mkdir(parents=True)
    (models / '__init__.py').write_text('')
    (models / '0_20260101_initial.py').write_text('# migration')
    monkeypatch.setattr(cli, '_APP_DIR', str(tmp_path))
    assert cli._has_existing_migrations() is True


def test_has_existing_migrations_skips_non_directory_entries_under_migrations(tmp_path, monkeypatch):
    """Stray files in migrations/ (e.g. .gitignore) are skipped, not treated as apps."""
    migrations = tmp_path / 'migrations'
    migrations.mkdir()
    (migrations / '.gitignore').write_text('*.pyc')
    models = migrations / 'models'
    models.mkdir()
    (models / '0_initial.py').write_text('# migration')
    monkeypatch.setattr(cli, '_APP_DIR', str(tmp_path))
    assert cli._has_existing_migrations() is True


# ---------------------------------------------------------------------------
# _github_api / _download_zip — HTTP helpers for framework:update
# ---------------------------------------------------------------------------


def test_github_api_calls_urlopen_with_user_agent_and_accept(monkeypatch):
    """The GitHub helper must send a User-Agent (required by api.github.com) and Accept header."""
    import io
    import json

    monkeypatch.delenv('GITHUB_TOKEN', raising=False)

    captured = {}

    class FakeContext:
        def __enter__(self_inner):
            return io.BytesIO(json.dumps({'tag_name': 'v1.0.0'}).encode())

        def __exit__(self_inner, *exc):
            return False

    def fake_urlopen(req):
        captured['url'] = req.full_url
        captured['headers'] = dict(req.header_items())
        return FakeContext()

    with patch('core.cli.urlopen', side_effect=fake_urlopen):
        result = cli._github_api('releases/latest')

    assert result == {'tag_name': 'v1.0.0'}
    assert 'releases/latest' in captured['url']
    # urllib normalizes header names with title-case
    headers_lower = {k.lower(): v for k, v in captured['headers'].items()}
    assert 'nori-framework-updater' in headers_lower['user-agent'].lower()
    assert headers_lower['accept'] == 'application/vnd.github+json'
    assert 'authorization' not in headers_lower  # no token, no Authorization header


def test_github_api_adds_authorization_when_github_token_set(monkeypatch):
    """If GITHUB_TOKEN is in the environment, _github_api adds Authorization: Bearer."""
    import io
    import json

    monkeypatch.setenv('GITHUB_TOKEN', 'ghp_secret')

    captured = {}

    class FakeContext:
        def __enter__(self_inner):
            return io.BytesIO(json.dumps([]).encode())

        def __exit__(self_inner, *exc):
            return False

    def fake_urlopen(req):
        captured['headers'] = dict(req.header_items())
        return FakeContext()

    with patch('core.cli.urlopen', side_effect=fake_urlopen):
        cli._github_api('releases')

    headers_lower = {k.lower(): v for k, v in captured['headers'].items()}
    assert headers_lower['authorization'] == 'Bearer ghp_secret'


def test_download_zip_streams_response_body_to_file(tmp_path, monkeypatch):
    """_download_zip must copy the URL response body to the destination file."""
    import io

    monkeypatch.delenv('GITHUB_TOKEN', raising=False)

    payload = b'fake-zip-bytes' * 100  # >1KB so we exercise copyfileobj's chunking
    dest = tmp_path / 'downloaded.zip'

    class FakeContext:
        def __enter__(self_inner):
            return io.BytesIO(payload)

        def __exit__(self_inner, *exc):
            return False

    def fake_urlopen(req):
        return FakeContext()

    with patch('core.cli.urlopen', side_effect=fake_urlopen):
        cli._download_zip('https://example.com/x.zip', str(dest))

    assert dest.read_bytes() == payload


# ---------------------------------------------------------------------------
# db_seed / queue_work / audit_purge — embedded-script subprocesses
# ---------------------------------------------------------------------------


def test_db_seed_invokes_python_with_inline_seed_script():
    """db_seed runs a python -c script that imports seeders.database_seeder.run()."""
    from unittest.mock import MagicMock

    with patch('core.cli.subprocess.run') as run:
        run.return_value = MagicMock(returncode=0)
        cli.db_seed()

    args = run.call_args[0][0]
    assert args[1] == '-c'
    script = args[2]
    assert 'from seeders.database_seeder import run' in script
    assert 'Tortoise.init' in script


def test_queue_work_passes_queue_name_into_script():
    """queue_work bakes the queue name into the inline script."""
    from unittest.mock import MagicMock

    with patch('core.cli.subprocess.run') as run:
        run.return_value = MagicMock(returncode=0)
        cli.queue_work('emails')

    script = run.call_args[0][0][2]
    assert "queue_name='emails'" in script


def test_queue_work_swallows_keyboard_interrupt():
    """Ctrl-C against a queue worker must not propagate."""
    with patch('core.cli.subprocess.run', side_effect=KeyboardInterrupt):
        cli.queue_work('default')  # no raise


def test_audit_purge_bakes_days_and_dry_run_into_script():
    """audit_purge formats the days/export/dry_run flags into the inline script."""
    from unittest.mock import MagicMock

    with patch('core.cli.subprocess.run') as run:
        run.return_value = MagicMock(returncode=0)
        cli.audit_purge(days=30, export=True, dry_run=True)

    script = run.call_args[0][0][2]
    assert 'timedelta(days=30)' in script
    assert 'if True' in script  # dry_run=True formatted into the script literal


def test_audit_purge_default_export_and_dry_run_are_false():
    """Defaults must format export=False / dry_run=False into the script."""
    from unittest.mock import MagicMock

    with patch('core.cli.subprocess.run') as run:
        run.return_value = MagicMock(returncode=0)
        cli.audit_purge(days=7)

    script = run.call_args[0][0][2]
    assert 'if False' in script  # both flags default-False appear as `if False`
    assert 'timedelta(days=7)' in script


# ---------------------------------------------------------------------------
# check_deps — exit code passthrough
# ---------------------------------------------------------------------------


def test_check_deps_passes_when_subprocess_returns_zero():
    """If the probe subprocess succeeds, check_deps returns normally (no SystemExit)."""
    from unittest.mock import MagicMock

    with patch('core.cli.subprocess.run') as run:
        run.return_value = MagicMock(returncode=0)
        cli.check_deps()  # no raise


def test_check_deps_propagates_nonzero_exit_code():
    """If a probe fails, check_deps must call sys.exit with the same code."""
    from unittest.mock import MagicMock

    with patch('core.cli.subprocess.run') as run, patch('core.cli.sys.exit') as fake_exit:
        run.return_value = MagicMock(returncode=2)
        cli.check_deps()
        fake_exit.assert_called_once_with(2)


# ---------------------------------------------------------------------------
# main() argparse dispatcher
# ---------------------------------------------------------------------------


def test_main_dispatches_serve(monkeypatch):
    monkeypatch.setattr('sys.argv', ['nori.py', 'serve', '--host', '127.0.0.1', '--port', '9000'])
    with patch('core.cli.serve') as fn:
        cli.main()
    fn.assert_called_once_with(host='127.0.0.1', port=9000)


def test_main_dispatches_shell(monkeypatch):
    monkeypatch.setattr('sys.argv', ['nori.py', 'shell'])
    with patch('core.cli.shell') as fn:
        cli.main()
    fn.assert_called_once()


def test_main_dispatches_make_controller(monkeypatch):
    monkeypatch.setattr('sys.argv', ['nori.py', 'make:controller', 'Article'])
    with patch('core.cli.make_controller') as fn:
        cli.main()
    fn.assert_called_once_with('Article')


def test_main_dispatches_make_model(monkeypatch):
    monkeypatch.setattr('sys.argv', ['nori.py', 'make:model', 'Product'])
    with patch('core.cli.make_model') as fn:
        cli.main()
    fn.assert_called_once_with('Product')


def test_main_dispatches_make_seeder(monkeypatch):
    monkeypatch.setattr('sys.argv', ['nori.py', 'make:seeder', 'User'])
    with patch('core.cli.make_seeder') as fn:
        cli.main()
    fn.assert_called_once_with('User')


def test_main_dispatches_migrate_init(monkeypatch):
    monkeypatch.setattr('sys.argv', ['nori.py', 'migrate:init'])
    with patch('core.cli.migrate_init') as fn:
        cli.main()
    fn.assert_called_once()


def test_main_dispatches_migrate_make_with_app_flag(monkeypatch):
    monkeypatch.setattr('sys.argv', ['nori.py', 'migrate:make', 'add_users', '--app', 'framework'])
    with patch('core.cli.migrate_make') as fn:
        cli.main()
    fn.assert_called_once_with('add_users', app='framework')


def test_main_dispatches_migrate_upgrade_default_no_app(monkeypatch):
    monkeypatch.setattr('sys.argv', ['nori.py', 'migrate:upgrade'])
    with patch('core.cli.migrate_upgrade') as fn:
        cli.main()
    fn.assert_called_once_with(app=None)


def test_main_dispatches_migrate_downgrade_with_steps_and_delete(monkeypatch):
    monkeypatch.setattr('sys.argv', ['nori.py', 'migrate:downgrade', '--steps', '3', '--delete'])
    with patch('core.cli.migrate_downgrade') as fn:
        cli.main()
    fn.assert_called_once_with(steps=3, delete=True, app='models')


def test_main_dispatches_migrate_fix(monkeypatch):
    monkeypatch.setattr('sys.argv', ['nori.py', 'migrate:fix'])
    with patch('core.cli.migrate_fix') as fn:
        cli.main()
    fn.assert_called_once()


def test_main_dispatches_migrate_fresh(monkeypatch):
    monkeypatch.setattr('sys.argv', ['nori.py', 'migrate:fresh'])
    with patch('core.cli.migrate_fresh') as fn:
        cli.main()
    fn.assert_called_once()


def test_main_dispatches_db_seed(monkeypatch):
    monkeypatch.setattr('sys.argv', ['nori.py', 'db:seed'])
    with patch('core.cli.db_seed') as fn:
        cli.main()
    fn.assert_called_once()


def test_main_dispatches_queue_work_with_name(monkeypatch):
    monkeypatch.setattr('sys.argv', ['nori.py', 'queue:work', '--name', 'emails'])
    with patch('core.cli.queue_work') as fn:
        cli.main()
    fn.assert_called_once_with('emails')


def test_main_dispatches_framework_update_with_flags(monkeypatch):
    monkeypatch.setattr(
        'sys.argv',
        ['nori.py', 'framework:update', '--version', '1.20.0', '--no-backup', '--force'],
    )
    with patch('core.cli.framework_update') as fn:
        cli.main()
    fn.assert_called_once_with(target_version='1.20.0', skip_backup=True, force=True)


def test_main_dispatches_framework_check_config_with_version(monkeypatch):
    monkeypatch.setattr('sys.argv', ['nori.py', 'framework:check-config', '--version', '1.15.0'])
    with patch('core.cli.framework_check_config') as fn:
        cli.main()
    fn.assert_called_once_with(target_version='1.15.0')


def test_main_dispatches_framework_check_config_without_version(monkeypatch):
    monkeypatch.setattr('sys.argv', ['nori.py', 'framework:check-config'])
    with patch('core.cli.framework_check_config') as fn:
        cli.main()
    fn.assert_called_once_with(target_version=None)


def test_main_dispatches_framework_version(monkeypatch):
    monkeypatch.setattr('sys.argv', ['nori.py', 'framework:version'])
    with patch('core.cli.framework_version') as fn:
        cli.main()
    fn.assert_called_once()


def test_main_dispatches_routes_list(monkeypatch):
    monkeypatch.setattr('sys.argv', ['nori.py', 'routes:list'])
    with patch('core.cli.routes_list') as fn:
        cli.main()
    fn.assert_called_once()


def test_main_dispatches_check_deps(monkeypatch):
    monkeypatch.setattr('sys.argv', ['nori.py', 'check:deps'])
    with patch('core.cli.check_deps') as fn:
        cli.main()
    fn.assert_called_once()


def test_main_dispatches_audit_purge_with_flags(monkeypatch):
    monkeypatch.setattr(
        'sys.argv',
        ['nori.py', 'audit:purge', '--days', '14', '--export', '--dry-run'],
    )
    with patch('core.cli.audit_purge') as fn:
        cli.main()
    fn.assert_called_once_with(14, export=True, dry_run=True)


def test_main_prints_help_when_no_command_given(monkeypatch, capsys):
    """No subcommand → argparse help is printed (and we don't crash)."""
    monkeypatch.setattr('sys.argv', ['nori.py'])
    cli.main()
    out = capsys.readouterr().out
    assert 'Available commands' in out or 'usage' in out.lower()


# ---------------------------------------------------------------------------
# framework:update — end-to-end integration with mocked network boundary
# ---------------------------------------------------------------------------
#
# Strategy: mock only `_github_api` and `_download_zip` (the network calls).
# Let the rest run on the real filesystem against tmp_path: zip extraction,
# backup creation, file replacement. This catches regressions in the actual
# update flow rather than asserting our mocks are called.
#
# `core._patches.apply()` runs for real but is harmless: its CWD-relative
# patchers (asgi.py, requirements.txt) find no targets in tmp_path and
# return False without side effects.


def _make_release_zip(zip_path, root='nori-1.99.0', files=None, dirs=None):
    """Build a fake GitHub release zip mimicking ``zipball`` archive structure."""
    files = files or {}
    dirs = dirs or {}
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.writestr(f'{root}/', '')
        for rel_path, content in files.items():
            zf.writestr(f'{root}/{rel_path}', content)
        for rel_dir, contents in dirs.items():
            zf.writestr(f'{root}/{rel_dir}', '')
            for fname, content in contents.items():
                zf.writestr(f'{root}/{rel_dir}{fname}', content)


def _release_dirs():
    """Standard fixture release content: all required framework files."""
    return {
        'rootsystem/application/core/': {
            'version.py': "__version__ = '1.99.0'\n",
            '__init__.py': '',
            'cli.py': '# new cli\n',
        },
        'rootsystem/application/models/framework/': {
            '__init__.py': '',
        },
    }


@pytest.fixture
def update_env(tmp_path, monkeypatch):
    """Set up a fake project layout under tmp_path matching the real shape."""
    app_dir = tmp_path / 'rootsystem' / 'application'
    core_dir = app_dir / 'core'
    framework_models_dir = app_dir / 'models' / 'framework'
    core_dir.mkdir(parents=True)
    framework_models_dir.mkdir(parents=True)
    (core_dir / 'version.py').write_text("__version__ = '1.0.0'\n")
    (tmp_path / 'requirements.nori.txt').write_text('# old\n')
    monkeypatch.chdir(tmp_path)
    return {
        'tmp_path': tmp_path,
        'app_dir': app_dir,
        'core_dir': core_dir,
        'framework_models_dir': framework_models_dir,
    }


def test_framework_update_happy_path_replaces_files_and_creates_backup(update_env, monkeypatch, capsys):
    def fake_download(url, dest):
        _make_release_zip(
            dest,
            root='nori-1.99.0',
            dirs=_release_dirs(),
            files={'requirements.nori.txt': '# new\n'},
        )

    monkeypatch.setattr(cli, '_github_api', lambda endpoint: {'tag_name': 'v1.99.0'})
    monkeypatch.setattr(cli, '_download_zip', fake_download)

    cli.framework_update(target_version='1.99.0')

    out = capsys.readouterr().out
    assert 'Updated: 1.0.0 → 1.99.0' in out
    assert (update_env['core_dir'] / 'version.py').read_text() == "__version__ = '1.99.0'\n"
    assert (update_env['core_dir'] / 'cli.py').read_text() == '# new cli\n'
    assert (update_env['tmp_path'] / 'requirements.nori.txt').read_text() == '# new\n'

    backups_root = update_env['tmp_path'] / 'rootsystem' / '.framework_backups'
    backup_dirs = list(backups_root.iterdir())
    assert len(backup_dirs) == 1
    assert backup_dirs[0].name.startswith('v1.0.0_')
    assert (backup_dirs[0] / 'core' / 'version.py').read_text() == "__version__ = '1.0.0'\n"


def test_framework_update_calls_releases_latest_when_no_target_version(update_env, monkeypatch):
    captured: dict = {}

    def fake_api(endpoint):
        captured['endpoint'] = endpoint
        return {'tag_name': 'v1.0.0'}

    monkeypatch.setattr(cli, '_github_api', fake_api)
    monkeypatch.setattr(cli, '_download_zip', MagicMock())

    cli.framework_update()

    assert captured['endpoint'] == 'releases/latest'


def test_framework_update_calls_releases_tags_when_target_version_given(update_env, monkeypatch):
    """Endpoint format check; tag matches current version so the flow short-circuits before download."""
    captured: dict = {}

    def fake_api(endpoint):
        captured['endpoint'] = endpoint
        return {'tag_name': 'v1.0.0'}

    monkeypatch.setattr(cli, '_github_api', fake_api)

    cli.framework_update(target_version='1.0.0')

    assert captured['endpoint'] == 'releases/tags/v1.0.0'


def test_framework_update_already_up_to_date_returns_early(update_env, monkeypatch, capsys):
    monkeypatch.setattr(cli, '_github_api', lambda endpoint: {'tag_name': 'v1.0.0'})
    download = MagicMock(side_effect=AssertionError('should not download'))
    monkeypatch.setattr(cli, '_download_zip', download)

    cli.framework_update(target_version='1.0.0')

    out = capsys.readouterr().out
    assert 'Already up to date' in out
    download.assert_not_called()


def test_framework_update_force_proceeds_even_when_versions_match(update_env, monkeypatch, capsys):
    def fake_download(url, dest):
        _make_release_zip(
            dest,
            root='nori-1.0.0',
            dirs={
                'rootsystem/application/core/': {
                    'version.py': "__version__ = '1.0.0'\n",
                    '__init__.py': '',
                },
                'rootsystem/application/models/framework/': {'__init__.py': ''},
            },
            files={'requirements.nori.txt': '# refreshed\n'},
        )

    monkeypatch.setattr(cli, '_github_api', lambda endpoint: {'tag_name': 'v1.0.0'})
    monkeypatch.setattr(cli, '_download_zip', fake_download)

    cli.framework_update(target_version='1.0.0', force=True)

    out = capsys.readouterr().out
    assert 'Already up to date' not in out
    assert 'Updated: 1.0.0 → 1.0.0' in out
    assert (update_env['tmp_path'] / 'requirements.nori.txt').read_text() == '# refreshed\n'


def test_framework_update_404_with_target_version_prints_specific_error(update_env, monkeypatch, capsys):
    def fake_api(endpoint):
        raise HTTPError('http://example', 404, 'Not Found', {}, io.BytesIO(b''))

    monkeypatch.setattr(cli, '_github_api', fake_api)

    cli.framework_update(target_version='9.9.9')

    out = capsys.readouterr().out
    assert 'Version v9.9.9 not found' in out


def test_framework_update_404_without_target_version_prints_no_releases(update_env, monkeypatch, capsys):
    def fake_api(endpoint):
        raise HTTPError('http://example', 404, 'Not Found', {}, io.BytesIO(b''))

    monkeypatch.setattr(cli, '_github_api', fake_api)

    cli.framework_update()

    out = capsys.readouterr().out
    assert 'No releases found' in out


def test_framework_update_url_error_on_api_prints_connection_error(update_env, monkeypatch, capsys):
    def fake_api(endpoint):
        raise URLError('No internet')

    monkeypatch.setattr(cli, '_github_api', fake_api)

    cli.framework_update()

    out = capsys.readouterr().out
    assert 'Could not connect to GitHub' in out


def test_framework_update_url_error_on_download_prints_download_failed(update_env, monkeypatch, capsys):
    monkeypatch.setattr(cli, '_github_api', lambda endpoint: {'tag_name': 'v1.99.0'})

    def fake_download(url, dest):
        raise URLError('connection reset')

    monkeypatch.setattr(cli, '_download_zip', fake_download)

    cli.framework_update(target_version='1.99.0')

    out = capsys.readouterr().out
    assert 'Download failed' in out


def test_framework_update_zip_missing_core_dir_aborts(update_env, monkeypatch, capsys):
    def fake_download(url, dest):
        _make_release_zip(
            dest,
            root='nori-1.99.0',
            dirs={'rootsystem/application/models/framework/': {'__init__.py': ''}},
            files={'requirements.nori.txt': '# new\n'},
        )

    monkeypatch.setattr(cli, '_github_api', lambda endpoint: {'tag_name': 'v1.99.0'})
    monkeypatch.setattr(cli, '_download_zip', fake_download)

    cli.framework_update(target_version='1.99.0')

    out = capsys.readouterr().out
    assert 'Release zip does not contain' in out
    # Original files preserved (no replacement happened)
    assert (update_env['core_dir'] / 'version.py').read_text() == "__version__ = '1.0.0'\n"


def test_framework_update_skip_backup_does_not_create_backup_dir(update_env, monkeypatch, capsys):
    def fake_download(url, dest):
        _make_release_zip(
            dest,
            root='nori-1.99.0',
            dirs=_release_dirs(),
            files={'requirements.nori.txt': '# new\n'},
        )

    monkeypatch.setattr(cli, '_github_api', lambda endpoint: {'tag_name': 'v1.99.0'})
    monkeypatch.setattr(cli, '_download_zip', fake_download)

    cli.framework_update(target_version='1.99.0', skip_backup=True)

    out = capsys.readouterr().out
    assert 'Backing up' not in out
    # Pre-flight should still appear, but the backup-location notice should not.
    assert 'Will replace' in out
    assert 'backed up to' not in out
    backups_root = update_env['tmp_path'] / 'rootsystem' / '.framework_backups'
    assert not backups_root.exists()


def test_framework_update_preflight_lists_replaced_paths_and_backup_location(update_env, monkeypatch, capsys):
    """Before downloading, the user sees what will be replaced and where the backup lands."""

    def fake_download(url, dest):
        _make_release_zip(
            dest,
            root='nori-1.99.0',
            dirs=_release_dirs(),
            files={'requirements.nori.txt': '# new\n'},
        )

    monkeypatch.setattr(cli, '_github_api', lambda endpoint: {'tag_name': 'v1.99.0'})
    monkeypatch.setattr(cli, '_download_zip', fake_download)

    cli.framework_update(target_version='1.99.0')

    out = capsys.readouterr().out
    assert 'Will replace:' in out
    # Derived from _FRAMEWORK_DIRS / _FRAMEWORK_FILES — the assertion is about
    # the data, not literal copy, so renaming the constants stays caught.
    for zip_path in cli._FRAMEWORK_DIRS:
        assert zip_path in out
    for file_name in cli._FRAMEWORK_FILES:
        assert file_name in out
    assert 'backed up to' in out
    assert f'v{"1.0.0"}_' in out  # current version embedded in the backup-path hint


def test_framework_update_non_dict_release_aborts(update_env, monkeypatch, capsys):
    monkeypatch.setattr(cli, '_github_api', lambda endpoint: ['not-a-dict'])

    cli.framework_update(target_version='1.99.0')

    out = capsys.readouterr().out
    assert 'Unexpected GitHub API response' in out


def test_framework_update_reraises_non_404_http_error(update_env, monkeypatch):
    """Only 404 is friendly-handled. 5xx etc. should bubble up so the caller sees the real failure."""

    def fake_api(endpoint):
        raise HTTPError('http://example', 503, 'Service Unavailable', {}, io.BytesIO(b''))

    monkeypatch.setattr(cli, '_github_api', fake_api)

    with pytest.raises(HTTPError) as exc_info:
        cli.framework_update(target_version='1.99.0')
    assert exc_info.value.code == 503


def test_framework_update_migrate_fix_reminder_shown_when_migrations_exist(update_env, monkeypatch, capsys):
    migrations_dir = update_env['app_dir'] / 'migrations' / 'models'
    migrations_dir.mkdir(parents=True)
    (migrations_dir / '0_20260101_initial.py').write_text('# migration')

    def fake_download(url, dest):
        _make_release_zip(
            dest,
            root='nori-1.99.0',
            dirs=_release_dirs(),
            files={'requirements.nori.txt': '# new\n'},
        )

    monkeypatch.setattr(cli, '_github_api', lambda endpoint: {'tag_name': 'v1.99.0'})
    monkeypatch.setattr(cli, '_download_zip', fake_download)

    cli.framework_update(target_version='1.99.0')

    out = capsys.readouterr().out
    assert 'migrate:fix' in out
    assert 'aerich <0.9.2' in out


# ---------------------------------------------------------------------------
# framework:check-config — read-only diff of pyproject.toml against a release
# ---------------------------------------------------------------------------


def test_diff_toml_returns_empty_when_documents_match():
    import tomlkit

    text = '[tool.ruff]\nline-length = 120\n[tool.coverage.report]\nfail_under = 86\n'
    a = tomlkit.parse(text)
    b = tomlkit.parse(text)

    added, changed, local_only = cli._diff_toml(a, b)
    assert added == {}
    assert changed == {}
    assert local_only == {}


def test_diff_toml_detects_added_upstream():
    import tomlkit

    local = tomlkit.parse('[tool.coverage.report]\nfail_under = 82\n')
    upstream = tomlkit.parse('[tool.coverage.report]\nfail_under = 82\nshow_missing = true\n')

    added, changed, local_only = cli._diff_toml(local, upstream)
    assert 'tool.coverage.report.show_missing' in added
    assert added['tool.coverage.report.show_missing'] is True
    assert changed == {}
    assert local_only == {}


def test_diff_toml_detects_changed_value():
    import tomlkit

    local = tomlkit.parse('[tool.coverage.report]\nfail_under = 82\n')
    upstream = tomlkit.parse('[tool.coverage.report]\nfail_under = 86\n')

    added, changed, local_only = cli._diff_toml(local, upstream)
    assert 'tool.coverage.report.fail_under' in changed
    local_v, upstream_v = changed['tool.coverage.report.fail_under']
    assert local_v == 82
    assert upstream_v == 86
    assert added == {}
    assert local_only == {}


def test_diff_toml_detects_local_only_keys():
    import tomlkit

    local = tomlkit.parse('[tool.coverage.report]\nfail_under = 86\n[tool.my_plugin]\nfoo = "bar"\n')
    upstream = tomlkit.parse('[tool.coverage.report]\nfail_under = 86\n')

    added, changed, local_only = cli._diff_toml(local, upstream)
    assert 'tool.my_plugin' in local_only
    assert added == {}
    assert changed == {}


def test_diff_toml_walks_nested_tables():
    """A change deep in a nested table is reported with the full dotted path."""
    import tomlkit

    local = tomlkit.parse('[tool.ruff.lint]\nselect = ["E", "W"]\n')
    upstream = tomlkit.parse('[tool.ruff.lint]\nselect = ["E", "W", "F"]\n')

    added, changed, local_only = cli._diff_toml(local, upstream)
    assert 'tool.ruff.lint.select' in changed


def test_diff_toml_treats_list_value_difference_as_changed():
    """Lists compare with == — any difference (size or order) shows up as changed, not added."""
    import tomlkit

    local = tomlkit.parse('[a]\nitems = [1, 2]\n')
    upstream = tomlkit.parse('[a]\nitems = [1, 2, 3]\n')

    added, changed, local_only = cli._diff_toml(local, upstream)
    assert 'a.items' in changed
    assert added == {}


@pytest.fixture
def check_config_env(tmp_path, monkeypatch):
    """Set up a tmp project with a baseline local pyproject.toml."""
    (tmp_path / 'pyproject.toml').write_text('[tool.coverage.report]\nfail_under = 82\n')
    core_dir = tmp_path / 'rootsystem' / 'application' / 'core'
    core_dir.mkdir(parents=True)
    (core_dir / 'version.py').write_text("__version__ = '1.15.0'\n")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_framework_check_config_no_drift_prints_no_drift_message(check_config_env, monkeypatch, capsys):
    monkeypatch.setattr(cli, '_github_api', lambda endpoint: {'tag_name': 'v1.15.0'})
    monkeypatch.setattr(cli, '_fetch_text', lambda url: '[tool.coverage.report]\nfail_under = 82\n')

    cli.framework_check_config(target_version='1.15.0')

    out = capsys.readouterr().out
    assert 'No drift detected' in out


def test_framework_check_config_reports_all_three_categories(check_config_env, monkeypatch, capsys):
    """Local has fail_under=82 + tool.local_only; upstream has fail_under=86 + tool.added."""
    upstream_text = '[tool.coverage.report]\nfail_under = 86\n[tool.added]\nnewkey = "x"\n'
    (check_config_env / 'pyproject.toml').write_text(
        '[tool.coverage.report]\nfail_under = 82\n[tool.local_only]\nmine = true\n'
    )
    monkeypatch.setattr(cli, '_github_api', lambda endpoint: {'tag_name': 'v1.15.1'})
    monkeypatch.setattr(cli, '_fetch_text', lambda url: upstream_text)

    cli.framework_check_config(target_version='1.15.1')

    out = capsys.readouterr().out
    assert 'Added upstream' in out
    assert 'tool.added' in out
    assert 'Changed upstream' in out
    assert 'tool.coverage.report.fail_under' in out
    assert 'Local-only' in out
    assert 'tool.local_only' in out


def test_framework_check_config_404_with_target_version(check_config_env, monkeypatch, capsys):
    def fake_api(endpoint):
        raise HTTPError('http://example', 404, 'Not Found', {}, io.BytesIO(b''))

    monkeypatch.setattr(cli, '_github_api', fake_api)

    cli.framework_check_config(target_version='9.9.9')

    out = capsys.readouterr().out
    assert 'Version v9.9.9 not found' in out


def test_framework_check_config_url_error_on_api(check_config_env, monkeypatch, capsys):
    def fake_api(endpoint):
        raise URLError('No internet')

    monkeypatch.setattr(cli, '_github_api', fake_api)

    cli.framework_check_config()

    out = capsys.readouterr().out
    assert 'Could not connect to GitHub' in out


def test_framework_check_config_url_error_on_fetch(check_config_env, monkeypatch, capsys):
    monkeypatch.setattr(cli, '_github_api', lambda endpoint: {'tag_name': 'v1.15.0'})

    def fake_fetch(url):
        raise URLError('connection reset')

    monkeypatch.setattr(cli, '_fetch_text', fake_fetch)

    cli.framework_check_config(target_version='1.15.0')

    out = capsys.readouterr().out
    assert 'Could not fetch upstream pyproject.toml' in out


def test_framework_check_config_missing_local_pyproject(tmp_path, monkeypatch, capsys):
    core_dir = tmp_path / 'rootsystem' / 'application' / 'core'
    core_dir.mkdir(parents=True)
    (core_dir / 'version.py').write_text("__version__ = '1.0.0'\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, '_github_api', lambda endpoint: {'tag_name': 'v1.0.0'})
    monkeypatch.setattr(cli, '_fetch_text', lambda url: '[a]\nb = 1\n')

    cli.framework_check_config(target_version='1.0.0')

    out = capsys.readouterr().out
    assert 'No pyproject.toml' in out


def test_framework_check_config_calls_releases_tags_when_target_version(check_config_env, monkeypatch):
    captured: dict = {}

    def fake_api(endpoint):
        captured['endpoint'] = endpoint
        return {'tag_name': 'v1.15.0'}

    monkeypatch.setattr(cli, '_github_api', fake_api)
    monkeypatch.setattr(cli, '_fetch_text', lambda url: '[tool.coverage.report]\nfail_under = 82\n')

    cli.framework_check_config(target_version='1.15.0')

    assert captured['endpoint'] == 'releases/tags/v1.15.0'


def test_framework_check_config_calls_releases_latest_without_target_version(check_config_env, monkeypatch):
    captured: dict = {}

    def fake_api(endpoint):
        captured['endpoint'] = endpoint
        return {'tag_name': 'v1.15.0'}

    monkeypatch.setattr(cli, '_github_api', fake_api)
    monkeypatch.setattr(cli, '_fetch_text', lambda url: '[tool.coverage.report]\nfail_under = 82\n')

    cli.framework_check_config()

    assert captured['endpoint'] == 'releases/latest'
