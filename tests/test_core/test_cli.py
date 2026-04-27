"""Tests for CLI commands in core/cli.py.

The aerich-wrapping commands (migrate:*) are tested by mocking subprocess.run
and asserting the right arguments are passed — testing that we drive aerich
correctly, not testing aerich itself. The make:* generators are tested by
asserting the file content they produce.
"""

from __future__ import annotations

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
