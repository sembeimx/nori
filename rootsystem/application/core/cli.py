"""Nori CLI — all framework commands live here so they update with core."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import textwrap
import zipfile
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_APP_DIR = os.path.join('rootsystem', 'application')

# ---------------------------------------------------------------------------
# Dev server
# ---------------------------------------------------------------------------


def serve(host: str = '0.0.0.0', port: int = 8000) -> None:  # noqa: S104 — dev server intentionally binds all interfaces (Docker, mobile testing)
    print('Booting up Nori Framework (Uvicorn) in development mode...')
    try:
        subprocess.run(
            [
                sys.executable,
                '-m',
                'uvicorn',
                'asgi:app',
                '--reload',
                '--reload-dir',
                '../templates',
                '--host',
                host,
                '--port',
                str(port),
            ],
            cwd=_APP_DIR,
        )
    except KeyboardInterrupt:
        pass


# ---------------------------------------------------------------------------
# Interactive shell
# ---------------------------------------------------------------------------


def shell() -> None:
    """Open an async Python REPL with Tortoise initialized and registered models in scope.

    Uses `python -m asyncio` so `await` works at the top level. Tortoise is
    booted before the prompt appears, and every model registered in
    `core.registry` is bound as a top-level name — so you can do:

        >>> users = await User.all()

    without any imports or connection setup.
    """
    print('Nori shell — async REPL with Tortoise + models loaded.')
    print('Use `await` at the top level. Press Ctrl-D or type exit() to quit.\n')

    startup = textwrap.dedent("""\
        import asyncio
        import sys
        sys.path.insert(0, '.')

        import settings
        from tortoise import Tortoise
        from core.registry import _models

        # Boot Tortoise synchronously before the REPL prompt appears.
        asyncio.get_event_loop().run_until_complete(
            Tortoise.init(config=settings.TORTOISE_ORM)
        )

        # Bind every registered model as a top-level name.
        globals().update(_models)

        if _models:
            print(f"Models in scope: {', '.join(sorted(_models))}")
        else:
            print("No models registered (rootsystem/application/models/__init__.py is empty).")
        print()
    """)

    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(startup)
        startup_path = f.name

    try:
        env = os.environ.copy()
        env['PYTHONSTARTUP'] = startup_path
        subprocess.run(
            [sys.executable, '-m', 'asyncio'],
            cwd=_APP_DIR,
            env=env,
        )
    except KeyboardInterrupt:
        pass
    finally:
        try:
            os.unlink(startup_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Scaffolding
# ---------------------------------------------------------------------------


def make_controller(name: str) -> None:
    filename = name.lower() + '.py'
    filepath = os.path.join(_APP_DIR, 'modules', filename)
    if os.path.exists(filepath):
        print(f'Error: {filepath} already exists.')
        return

    content = f"""from starlette.requests import Request
from starlette.responses import JSONResponse
from core.jinja import templates


class {name}Controller:

    async def list(self, request: Request):
        return JSONResponse({{"message": "{name} List"}})

    async def create(self, request: Request):
        pass
"""
    with open(filepath, 'w') as f:
        f.write(content)
    print(f'Controller created at: {filepath}')


def make_model(name: str) -> None:
    filename = name.lower() + '.py'
    filepath = os.path.join(_APP_DIR, 'models', filename)
    if os.path.exists(filepath):
        print(f'Error: {filepath} already exists.')
        return

    content = f"""from tortoise.models import Model
from tortoise import fields
from core.mixins.model import NoriModelMixin


class {name}(NoriModelMixin, Model):
    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=100)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = '{name.lower()}'
"""
    with open(filepath, 'w') as f:
        f.write(content)
    print(f'Model {name} created at: {filepath}')
    print(f"Don't forget to register the model in {_APP_DIR}/models/__init__.py")


def make_seeder(name: str) -> None:
    filename = name.lower() + '_seeder.py'
    filepath = os.path.join(_APP_DIR, 'seeders', filename)
    if os.path.exists(filepath):
        print(f'Error: {filepath} already exists.')
        return

    content = f"""\"\"\"Seeder for {name}.\"\"\"
# from models.{name.lower()} import {name}


async def run() -> None:
    \"\"\"Seed {name} data.\"\"\"
    # await {name}.create(name='Example')
    pass
"""
    with open(filepath, 'w') as f:
        f.write(content)
    print(f'Seeder created at: {filepath}')
    print("Don't forget to register it in seeders/database_seeder.py")


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------


def _quiet_env() -> dict[str, str]:
    """Subprocess env that silences Tortoise's `Module "X" has no models` noise.

    Tortoise emits a RuntimeWarning whenever a configured app contains no
    `Model` subclasses. In Nori's layout this is normal — the user's `models`
    app is empty on fresh projects, and aerich invokes Tortoise.init() during
    migrations. The warning isn't actionable, so we suppress RuntimeWarning in
    the aerich subprocess. Real registration bugs surface as failed queries
    or missing tables, not as this warning.
    """
    env = os.environ.copy()
    extra = 'ignore::RuntimeWarning'
    existing = env.get('PYTHONWARNINGS', '')
    env['PYTHONWARNINGS'] = f'{extra},{existing}' if existing else extra
    return env


_DEFAULT_APPS: tuple[str, ...] = ('framework', 'models')


def _read_tortoise_apps() -> tuple[str, ...]:
    """Read app names from `settings.TORTOISE_ORM['apps']` in the user project.

    Returns the keys in declaration order. Falls back to ('framework', 'models')
    if settings can't be loaded (e.g. uninstalled deps, broken settings file).
    The fallback preserves Nori's classic two-app layout so the CLI still does
    something sensible on a half-broken project.
    """
    script = (
        "import sys; sys.path.insert(0, '.')\n"
        'import settings\n'
        "for app in settings.TORTOISE_ORM.get('apps', {}).keys():\n"
        '    print(app)'
    )
    try:
        out = (
            subprocess.check_output(
                [sys.executable, '-c', script],
                cwd=_APP_DIR,
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return _DEFAULT_APPS
    apps = tuple(line.strip() for line in out.split('\n') if line.strip())
    return apps or _DEFAULT_APPS


def migrate_init() -> None:
    print('Initializing Aerich migrations...')
    subprocess.run(
        [sys.executable, '-m', 'aerich', 'init', '-t', 'settings.TORTOISE_ORM'],
        cwd=_APP_DIR,
        env=_quiet_env(),
    )
    # `aerich init-db` only initializes one app per invocation (the first one
    # in pyproject.toml). Loop over every app declared in settings.TORTOISE_ORM
    # so a single migrate:init bootstraps the framework, user models, and any
    # additional apps the user has wired in. Idempotent: an app that already
    # has migration files is skipped.
    for app in _read_tortoise_apps():
        migrations_dir = os.path.join(_APP_DIR, 'migrations', app)
        already_inited = os.path.isdir(migrations_dir) and any(
            f.endswith('.py') and f != '__init__.py' for f in os.listdir(migrations_dir)
        )
        if already_inited:
            print(f"  App '{app}' already initialized — skipping.")
            continue
        print(f"  Generating initial migrations and tables for app '{app}'...")
        subprocess.run(
            [sys.executable, '-m', 'aerich', '--app', app, 'init-db'],
            cwd=_APP_DIR,
            env=_quiet_env(),
        )


def migrate_make(name: str, app: str = 'models') -> None:
    print(f'Creating migration: {name} (app: {app})...')
    subprocess.run(
        [sys.executable, '-m', 'aerich', '--app', app, 'migrate', '--name', name],
        cwd=_APP_DIR,
        env=_quiet_env(),
    )


def migrate_upgrade(app: str | None = None) -> None:
    apps = [app] if app else list(_read_tortoise_apps())
    for a in apps:
        print(f'Running migrations (upgrade) for app: {a}...')
        subprocess.run(
            [sys.executable, '-m', 'aerich', '--app', a, 'upgrade'],
            cwd=_APP_DIR,
            env=_quiet_env(),
        )


def migrate_downgrade(steps: int = 1, delete: bool = False, app: str = 'models') -> None:
    print(f'Rolling back {steps} migration(s) for app: {app}...')
    cmd = [sys.executable, '-m', 'aerich', '--app', app, 'downgrade', '-v', str(steps)]
    if delete:
        cmd.append('-d')
    subprocess.run(cmd, cwd=_APP_DIR, env=_quiet_env())


def migrate_fix() -> None:
    print('Fixing migration files to current Aerich format...')
    subprocess.run(
        [sys.executable, '-m', 'aerich', 'fix-migrations'],
        cwd=_APP_DIR,
        env=_quiet_env(),
    )


def migrate_fresh() -> None:
    print('\n  Nori migrate:fresh')
    print('  ------------------')

    # 1. Check for DEBUG=true (safety)
    script_check = (
        "import sys, os; sys.path.insert(0, '.'); import settings\n"
        "print('DEBUG_TRUE' if getattr(settings, 'DEBUG', False) else 'DEBUG_FALSE')"
    )
    try:
        result = (
            subprocess.check_output(
                [sys.executable, '-c', script_check],
                cwd=_APP_DIR,
                stderr=subprocess.STDOUT,
            )
            .decode()
            .strip()
        )
    except subprocess.CalledProcessError as e:
        print(f'  Error: Could not read settings.py — {e.output.decode().strip()}')
        return

    if result != 'DEBUG_TRUE':
        print('  Error: migrate:fresh can only be run when DEBUG=true in settings.py')
        return

    # 2. Confirm action
    confirm = input('  This will WIPE the database and reset migrations. Continue? [yes/no]: ')
    if confirm.lower() != 'yes':
        print('  Aborted.')
        return

    # 3. Wipe database (DB-agnostic via Tortoise)
    print('\n  1. Wiping database tables (DB-agnostic)...')
    script_drop = (
        'import asyncio, sys, os\n'
        "sys.path.insert(0, '.')\n"
        'import settings\n'
        'from tortoise import Tortoise\n'
        'async def _drop():\n'
        '    await Tortoise.init(config=settings.TORTOISE_ORM)\n'
        '    await Tortoise._drop_databases()\n'
        '    # Re-create the empty database (needed for MySQL/Postgres where\n'
        '    # _drop_databases issues DROP DATABASE).  Mirrors the pattern\n'
        "    # used by Tortoise's own test runner.\n"
        '    await Tortoise.init(config=settings.TORTOISE_ORM, _create_db=True)\n'
        '    await Tortoise.close_connections()\n'
        'asyncio.run(_drop())\n'
    )
    subprocess.run([sys.executable, '-c', script_drop], cwd=_APP_DIR)

    # 4. Deleting all migration files (framework + models + any extra apps).
    #    Pre-1.8 the framework shipped its own migrations and `migrate:fresh`
    #    deliberately preserved `migrations/framework/`. Post-1.8 framework
    #    migrations are user-owned and engine-specific — but their content is
    #    derived from the same framework model definitions on every machine,
    #    so regenerating them is lossless. Wiping all apps keeps "fresh"
    #    honest to its name.
    print('  2. Deleting all migration files (will be regenerated)...')
    migrations_root = os.path.join(_APP_DIR, 'migrations')
    if os.path.exists(migrations_root):
        shutil.rmtree(migrations_root)
        print(f'     Deleted {migrations_root}')

    # 5. Regenerate migrations and apply them. migrate_init() reads apps from
    #    settings.TORTOISE_ORM, so any third-party app the user has wired in
    #    gets initialized too.
    print('  3. Regenerating migrations and applying them...')
    migrate_init()

    print('\n  Fresh database ready.')


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


def db_seed() -> None:
    print('Running database seeders...')
    script = (
        'import asyncio, sys, os\n'
        "sys.path.insert(0, '.')\n"
        'import settings\n'
        'from core.conf import configure; configure(settings)\n'
        'import models\n'
        'from tortoise import Tortoise\n'
        'async def _seed():\n'
        '    await Tortoise.init(config=settings.TORTOISE_ORM)\n'
        '    from seeders.database_seeder import run\n'
        '    await run()\n'
        '    await Tortoise.close_connections()\n'
        'asyncio.run(_seed())\n'
    )
    subprocess.run([sys.executable, '-c', script], cwd=_APP_DIR)


def queue_work(name: str) -> None:
    print(f'Starting queue worker for: {name}...')
    script = (
        'import asyncio, sys\n'
        "sys.path.insert(0, '.')\n"
        'import settings\n'
        'from core.conf import configure; configure(settings)\n'
        'import models\n'
        'from tortoise import Tortoise\n'
        'from core.queue_worker import work\n'
        'async def run_worker():\n'
        '    await Tortoise.init(config=settings.TORTOISE_ORM)\n'
        f"    await work(queue_name='{name}')\n"
        'asyncio.run(run_worker())\n'
    )
    try:
        subprocess.run([sys.executable, '-c', script], cwd=_APP_DIR)
    except KeyboardInterrupt:
        pass


# ---------------------------------------------------------------------------
# Framework update
# ---------------------------------------------------------------------------

_GITHUB_REPO = 'sembeimx/nori'
_GITHUB_API = 'https://api.github.com'
_CORE_DIR = os.path.join(_APP_DIR, 'core')
_FRAMEWORK_MODELS_DIR = os.path.join(_APP_DIR, 'models', 'framework')
_BACKUP_DIR = os.path.join('rootsystem', '.framework_backups')

_REQUIREMENTS_NORI_FILE = 'requirements.nori.txt'

# `migrations/framework/` is intentionally NOT here. Aerich emits engine-specific
# SQL (AUTOINCREMENT vs AUTO_INCREMENT vs SERIAL), so a single pre-generated
# migration cannot work across MySQL / Postgres / SQLite. From 1.8 onwards each
# site owns its own framework migrations, generated against its engine via
# `python3 nori.py migrate:init` on first install. Framework model definitions
# (in `models/framework/`) ARE shipped — aerich diffs them against the user's
# saved snapshot to generate engine-correct migrations on `migrate:make`.
_FRAMEWORK_DIRS = {
    'rootsystem/application/core/': _CORE_DIR,
    'rootsystem/application/models/framework/': _FRAMEWORK_MODELS_DIR,
}

# Individual files shipped by the framework that live OUTSIDE the directories
# above. Replaced wholesale on update just like the dirs (with backup).
_FRAMEWORK_FILES = {
    'requirements.nori.txt': _REQUIREMENTS_NORI_FILE,
}


def _get_current_version() -> str:
    version_file = os.path.join(_CORE_DIR, 'version.py')
    if not os.path.exists(version_file):
        return 'unknown'
    with open(version_file) as f:
        for line in f:
            if line.startswith('__version__'):
                return line.split('=')[1].strip().strip('\'"')
    return 'unknown'


def _github_api(endpoint: str) -> dict | list:
    url = f'{_GITHUB_API}/repos/{_GITHUB_REPO}/{endpoint}'
    req = Request(
        url,
        headers={
            'User-Agent': 'Nori-Framework-Updater',
            'Accept': 'application/vnd.github+json',
        },
    )
    token = os.environ.get('GITHUB_TOKEN', '')
    if token:
        req.add_header('Authorization', f'Bearer {token}')
    with urlopen(req) as resp:
        return json.loads(resp.read())


def _download_zip(url: str, dest: str) -> None:
    req = Request(url, headers={'User-Agent': 'Nori-Framework-Updater'})
    token = os.environ.get('GITHUB_TOKEN', '')
    if token:
        req.add_header('Authorization', f'Bearer {token}')
    with urlopen(req) as resp, open(dest, 'wb') as f:
        shutil.copyfileobj(resp, f)


def framework_update(target_version: str | None = None, skip_backup: bool = False, force: bool = False) -> None:
    """Update the framework core from a GitHub release."""
    current = _get_current_version()
    print('Nori framework:update')
    print(f'  Current version: {current}')

    try:
        if target_version:
            release = _github_api(f'releases/tags/v{target_version}')
        else:
            release = _github_api('releases/latest')
    except HTTPError as e:
        if e.code == 404:
            print(
                f'\n  Error: {"Version v" + target_version + " not found" if target_version else "No releases found"}.'
            )
            print(f'  Check https://github.com/{_GITHUB_REPO}/releases')
            return
        raise
    except URLError as e:
        print(f'\n  Error: Could not connect to GitHub — {e.reason}')
        print('  Check your internet connection or set GITHUB_TOKEN for private repos.')
        return

    if not isinstance(release, dict):
        print('\n  Error: Unexpected GitHub API response shape (not an object).')
        return
    tag = release['tag_name']
    version = tag.lstrip('v')
    print(f'  Target version:  {version} ({tag})')

    if version == current and not force:
        print('\n  Already up to date. Use --force to re-install.')
        return

    zip_url = f'https://github.com/{_GITHUB_REPO}/archive/refs/tags/{tag}.zip'
    print(f'\n  Downloading {tag}...')

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = os.path.join(tmp, 'release.zip')
        try:
            _download_zip(zip_url, zip_path)
        except (URLError, HTTPError) as e:
            print(f'  Error: Download failed — {e}')
            return

        with zipfile.ZipFile(zip_path) as zf:
            root_prefix = zf.namelist()[0].split('/')[0] + '/'

            extracted: dict[str, str] = {}
            for zip_rel_path, local_dir in _FRAMEWORK_DIRS.items():
                full_prefix = root_prefix + zip_rel_path
                extract_dir = os.path.join(tmp, zip_rel_path.replace('/', '_'))
                found = False
                for member in zf.namelist():
                    if member.startswith(full_prefix) and not member.endswith('/'):
                        found = True
                        relative_path = member[len(full_prefix) :]
                        dest_path = os.path.join(extract_dir, relative_path)
                        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                        with zf.open(member) as src, open(dest_path, 'wb') as dst:
                            shutil.copyfileobj(src, dst)
                if found:
                    extracted[local_dir] = extract_dir

            extracted_files: dict[str, str] = {}
            for zip_rel_file, local_file in _FRAMEWORK_FILES.items():
                member_name = root_prefix + zip_rel_file
                if member_name in zf.namelist():
                    temp_path = os.path.join(tmp, zip_rel_file.replace('/', '_'))
                    parent = os.path.dirname(temp_path)
                    if parent:
                        os.makedirs(parent, exist_ok=True)
                    with zf.open(member_name) as src, open(temp_path, 'wb') as dst:
                        shutil.copyfileobj(src, dst)
                    extracted_files[local_file] = temp_path

            if _CORE_DIR not in extracted:
                print('  Error: Release zip does not contain rootsystem/application/core/')
                print('  This release may not be compatible with your project structure.')
                return

        if not skip_backup:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_root = os.path.join(_BACKUP_DIR, f'v{current}_{timestamp}')
            os.makedirs(backup_root, exist_ok=True)
            for local_dir in extracted:
                if os.path.exists(local_dir):
                    rel_path = os.path.relpath(local_dir, _APP_DIR)
                    backup_dest = os.path.join(backup_root, rel_path)
                    print(f'  Backing up {local_dir} → {backup_dest}')
                    os.makedirs(os.path.dirname(backup_dest), exist_ok=True)
                    shutil.copytree(local_dir, backup_dest)
            for local_file in extracted_files:
                if os.path.exists(local_file):
                    backup_dest = os.path.join(backup_root, local_file)
                    print(f'  Backing up {local_file} → {backup_dest}')
                    parent = os.path.dirname(backup_dest)
                    if parent:
                        os.makedirs(parent, exist_ok=True)
                    shutil.copy2(local_file, backup_dest)

        for local_dir, extract_dir in extracted.items():
            label = os.path.relpath(local_dir, _APP_DIR)
            print(f'  Replacing {label}/ ...')
            if os.path.exists(local_dir):
                shutil.rmtree(local_dir)
            shutil.copytree(extract_dir, local_dir)

        for local_file, temp_path in extracted_files.items():
            print(f'  Replacing {local_file} ...')
            shutil.copy2(temp_path, local_file)

    # Reload patches from the freshly installed core. The OLD cli.py that is
    # currently executing was loaded into memory before the update, so any
    # patches added in the new release cannot fire from here. Clearing the
    # module from sys.modules and re-importing forces Python to read the
    # freshly installed bytecode from disk.
    sys.modules.pop('core._patches', None)
    try:
        from core import _patches

        patches = _patches.apply()
    except Exception as e:
        print(f'\n  Warning: could not load core._patches — {e}')
        patches = []

    if patches:
        print('\n  Applying patches...')
        for p in patches:
            print(f'    ✓ {p}')

    print(f'\n  Updated: {current} → {version}')
    print('  If framework models changed, generate a migration against your engine:')
    print('    python3 nori.py migrate:make <name> --app framework')
    print('    python3 nori.py migrate:upgrade --app framework')


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def audit_purge(days: int, export: bool = False, dry_run: bool = False) -> None:
    print(f'Purging audit log entries older than {days} days...')
    script = textwrap.dedent(f"""\
        import asyncio, sys, os, csv
        sys.path.insert(0, '.')
        import settings
        from core.conf import configure
        configure(settings)
        from tortoise import Tortoise
        from datetime import datetime, timedelta, timezone

        async def _purge():
            await Tortoise.init(config=settings.TORTOISE_ORM)
            from core.registry import get_model
            AuditLog = get_model('AuditLog')

            cutoff = datetime.now(timezone.utc) - timedelta(days={days})
            qs = AuditLog.filter(created_at__lt=cutoff)
            count = await qs.count()

            if count == 0:
                print("No entries to purge.")
                await Tortoise.close_connections()
                return

            if {dry_run}:
                print(f"Would purge {{count}} entries older than {days} days.")
                await Tortoise.close_connections()
                return

            if {export}:
                entries = await qs.order_by('created_at').all()
                filename = f"audit_log_export_{{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}}.csv"
                with open(filename, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(['id', 'user_id', 'action', 'model_name', 'record_id', 'changes', 'ip_address', 'request_id', 'created_at'])
                    for e in entries:
                        writer.writerow([e.id, e.user_id, e.action, e.model_name, e.record_id, e.changes, e.ip_address, e.request_id, e.created_at])
                print(f"Exported {{count}} entries to {{filename}}")

            await qs.delete()
            print(f"Purged {{count}} audit log entries older than {days} days.")
            await Tortoise.close_connections()

        asyncio.run(_purge())
    """)
    subprocess.run([sys.executable, '-c', script], cwd=_APP_DIR)


def routes_list() -> None:
    """Print all registered routes in a table format."""
    script = textwrap.dedent("""\
        import sys, os
        sys.path.insert(0, '.')
        import settings
        from core.conf import configure
        configure(settings)
        from routes import routes as app_routes
        from starlette.routing import Route, Mount, WebSocketRoute

        def _collect(routes, prefix=''):
            rows = []
            for route in routes:
                if isinstance(route, Mount):
                    sub_prefix = prefix + route.path
                    if route.routes:
                        rows.extend(_collect(route.routes, sub_prefix))
                    else:
                        rows.append((sub_prefix, 'MOUNT', route.name or ''))
                elif isinstance(route, WebSocketRoute):
                    rows.append((prefix + route.path, 'WS', route.name or ''))
                elif isinstance(route, Route):
                    methods = ','.join(sorted(route.methods - {'HEAD'})) if route.methods else 'ANY'
                    rows.append((prefix + route.path, methods, route.name or ''))
            return rows

        rows = _collect(app_routes)

        if not rows:
            print('No routes registered.')
            raise SystemExit(0)

        # Calculate column widths
        headers = ('Path', 'Methods', 'Name')
        widths = [len(h) for h in headers]
        for row in rows:
            for i, cell in enumerate(row):
                widths[i] = max(widths[i], len(cell))

        fmt = '  {{:<{}}}  {{:<{}}}  {{}}'.format(widths[0], widths[1])
        sep = '  ' + '-' * widths[0] + '  ' + '-' * widths[1] + '  ' + '-' * widths[2]

        print()
        print(fmt.format(*headers))
        print(sep)
        for row in rows:
            print(fmt.format(*row))
        print()
        print(f'  {len(rows)} route(s) registered.')
    """)
    subprocess.run([sys.executable, '-c', script], cwd=_APP_DIR)


def framework_version() -> None:
    print(f'Nori v{_get_current_version()}')


def check_deps() -> None:
    """Probe DB, cache, and throttle backends. Exit 1 if any are unreachable.

    Use as a pre-deploy or CI check after v1.11.0's fail-fast Redis behavior:
    instead of finding out at app boot that REDIS_URL is wrong, run this
    against your settings to verify dependency reachability up front.
    """
    script = textwrap.dedent("""\
        import asyncio, sys, os
        sys.path.insert(0, '.')
        import settings
        from core.conf import configure
        configure(settings)

        from core.cache import get_backend as get_cache_backend
        from core.http.throttle_backends import get_backend as get_throttle_backend

        async def _probe():
            results = []  # [(label, backend_kind, ok, error_msg)]

            # Database
            if getattr(settings, 'DB_ENABLED', False):
                from tortoise import Tortoise
                engine = getattr(settings, 'DB_ENGINE', 'unknown')
                try:
                    await Tortoise.init(config=settings.TORTOISE_ORM)
                    try:
                        conn = Tortoise.get_connection('default')
                        await conn.execute_query('SELECT 1')
                        results.append(('Database', engine, True, None))
                    finally:
                        await Tortoise.close_connections()
                except Exception as exc:
                    results.append(('Database', engine, False, str(exc)))
            else:
                results.append(('Database', 'disabled', True, None))

            # Cache
            cache_kind = getattr(settings, 'CACHE_BACKEND', 'memory')
            try:
                await get_cache_backend().verify()
                results.append(('Cache', cache_kind, True, None))
            except Exception as exc:
                results.append(('Cache', cache_kind, False, str(exc)))

            # Throttle
            throttle_kind = getattr(settings, 'THROTTLE_BACKEND', 'memory')
            try:
                await get_throttle_backend().verify()
                results.append(('Throttle', throttle_kind, True, None))
            except Exception as exc:
                results.append(('Throttle', throttle_kind, False, str(exc)))

            return results

        results = asyncio.run(_probe())

        print()
        for label, kind, ok, err in results:
            mark = '\\u2713' if ok else '\\u2717'
            line = f'  {mark} {label} ({kind})'
            if not ok:
                line += f': {err}'
            print(line)
        print()

        failed = [r for r in results if not r[2]]
        if failed:
            print(f'  {len(failed)} dependency check(s) failed.')
            raise SystemExit(1)
        print(f'  All {len(results)} dependency check(s) passed.')
    """)
    result = subprocess.run([sys.executable, '-c', script], cwd=_APP_DIR, env=_quiet_env())
    if result.returncode != 0:
        sys.exit(result.returncode)


# ---------------------------------------------------------------------------
# User command plugins
# ---------------------------------------------------------------------------


def _load_user_commands(subparsers) -> dict:
    """Discover and load user commands from the commands/ directory.

    Each Python file in ``commands/`` (excluding ``__init__.py`` and files
    starting with ``_``) must define a ``register(subparsers)`` function
    that adds one or more subparsers, and a ``handle(args)`` function
    that executes the command.

    Returns a dict mapping command names to their handle functions.
    """
    handlers: dict = {}
    # Anchor to the cli module file, not CWD. nori.py adds rootsystem/application
    # to sys.path but does NOT chdir into it, so a relative `Path('commands')`
    # would resolve against the user's CWD (typically the project root) and
    # silently miss the real commands/ dir at rootsystem/application/commands/.
    commands_dir = pathlib.Path(__file__).resolve().parent.parent / 'commands'

    if not commands_dir.is_dir():
        return handlers

    for filepath in sorted(commands_dir.glob('*.py')):
        if filepath.name.startswith('_') or filepath.name == '__init__.py':
            continue

        module_name = f'commands.{filepath.stem}'
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            print(f"  Warning: failed to load command '{filepath.name}': {exc}")
            continue

        register_fn = getattr(module, 'register', None)
        handle_fn = getattr(module, 'handle', None)
        if register_fn is None or handle_fn is None:
            print(f"  Warning: '{filepath.name}' missing register() or handle() — skipped")
            continue

        # Capture registered command names by comparing before/after
        before = set(subparsers._name_parser_map.keys()) if hasattr(subparsers, '_name_parser_map') else set()
        try:
            register_fn(subparsers)
        except Exception as exc:
            print(f"  Warning: register() in '{filepath.name}' failed: {exc}")
            continue
        after = set(subparsers._name_parser_map.keys()) if hasattr(subparsers, '_name_parser_map') else set()

        for cmd_name in after - before:
            handlers[cmd_name] = handle_fn

    return handlers


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description='Nori CLI')
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    serve_parser = subparsers.add_parser('serve', help='Start the dev server with hot reload')
    serve_parser.add_argument('--host', default='0.0.0.0', help='Bind address (default: 0.0.0.0)')  # noqa: S104 — dev server intentionally binds all interfaces
    serve_parser.add_argument('--port', type=int, default=8000, help='Port (default: 8000)')

    subparsers.add_parser('shell', help='Open an async REPL with Tortoise + registered models loaded')

    parser_controller = subparsers.add_parser('make:controller', help='Create a new controller')
    parser_controller.add_argument('name', type=str, help='Entity name (e.g. Product)')

    parser_model = subparsers.add_parser('make:model', help='Create a new Tortoise ORM model')
    parser_model.add_argument('name', type=str, help='Entity name (e.g. Product)')

    parser_seeder = subparsers.add_parser('make:seeder', help='Create a new database seeder')
    parser_seeder.add_argument('name', type=str, help='Entity name (e.g. User)')

    subparsers.add_parser('migrate:init', help='Initialize Aerich migration system')

    p_migrate = subparsers.add_parser('migrate:make', help='Create a new migration')
    p_migrate.add_argument('name', type=str, help='Migration name (e.g. add_users_table)')
    p_migrate.add_argument('--app', default='models', help='App label: models (default) or framework')

    p_upgrade = subparsers.add_parser('migrate:upgrade', help='Run pending migrations')
    p_upgrade.add_argument('--app', default=None, help='App label: models, framework, or omit for both')

    p_down = subparsers.add_parser('migrate:downgrade', help='Rollback migrations')
    p_down.add_argument('--steps', type=int, default=1, help='Number of migrations to roll back')
    p_down.add_argument('--delete', action='store_true', help='Delete migration files on downgrade')
    p_down.add_argument('--app', default='models', help='App label: models (default) or framework')

    subparsers.add_parser('migrate:fix', help='Fix migration files to current Aerich format')
    subparsers.add_parser('migrate:fresh', help='Drop DB + delete migrations + re-init (dev only)')

    subparsers.add_parser('db:seed', help='Run database seeders')

    parser_work = subparsers.add_parser('queue:work', help='Run the queue worker')
    parser_work.add_argument('--name', default='default', help='Queue name')

    parser_update = subparsers.add_parser('framework:update', help='Update the Nori core from GitHub')
    parser_update.add_argument('--version', default=None, help='Target version (e.g. 1.3.0). Defaults to latest.')
    parser_update.add_argument('--no-backup', action='store_true', help='Skip backing up the current core/')
    parser_update.add_argument('--force', action='store_true', help='Re-install even if already on the target version')

    subparsers.add_parser('framework:version', help='Show the current framework version')
    subparsers.add_parser('routes:list', help='List all registered routes')
    subparsers.add_parser('check:deps', help='Probe DB, cache, and throttle reachability (pre-deploy check)')

    audit_purge_parser = subparsers.add_parser('audit:purge', help='Purge old audit log entries')
    audit_purge_parser.add_argument(
        '--days', type=int, default=90, help='Delete entries older than N days (default: 90)'
    )
    audit_purge_parser.add_argument('--export', action='store_true', help='Export to CSV before deleting')
    audit_purge_parser.add_argument('--dry-run', action='store_true', help='Show count without deleting')

    # Load user commands from commands/ directory
    _user_handlers = _load_user_commands(subparsers)

    args = parser.parse_args()

    if args.command == 'serve':
        serve(host=args.host, port=args.port)
    elif args.command == 'shell':
        shell()
    elif args.command == 'make:controller':
        make_controller(args.name)
    elif args.command == 'make:model':
        make_model(args.name)
    elif args.command == 'make:seeder':
        make_seeder(args.name)
    elif args.command == 'migrate:init':
        migrate_init()
    elif args.command == 'migrate:make':
        migrate_make(args.name, app=args.app)
    elif args.command == 'migrate:upgrade':
        migrate_upgrade(app=args.app)
    elif args.command == 'migrate:downgrade':
        migrate_downgrade(steps=args.steps, delete=args.delete, app=args.app)
    elif args.command == 'migrate:fix':
        migrate_fix()
    elif args.command == 'migrate:fresh':
        migrate_fresh()
    elif args.command == 'db:seed':
        db_seed()
    elif args.command == 'queue:work':
        queue_work(args.name)
    elif args.command == 'framework:update':
        framework_update(target_version=args.version, skip_backup=args.no_backup, force=args.force)
    elif args.command == 'framework:version':
        framework_version()
    elif args.command == 'routes:list':
        routes_list()
    elif args.command == 'check:deps':
        check_deps()
    elif args.command == 'audit:purge':
        audit_purge(args.days, export=args.export, dry_run=args.dry_run)
    elif args.command in _user_handlers:
        _user_handlers[args.command](args)
    else:
        parser.print_help()
