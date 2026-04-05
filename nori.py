#!/usr/bin/env python3
from __future__ import annotations

import sys
import os
import subprocess
import argparse
import json
import shutil
import tempfile
import zipfile
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

_APP_DIR = os.path.join('rootsystem', 'application')


def serve(host='0.0.0.0', port=8000):
    print("Booting up Nori Framework (Uvicorn) in development mode...")
    try:
        subprocess.run([
            sys.executable, '-m', 'uvicorn',
            'asgi:app', '--reload',
            '--reload-dir', '../templates',
            '--host', host,
            '--port', str(port),
        ], cwd=_APP_DIR)
    except KeyboardInterrupt:
        pass


def make_controller(name):
    filename = name.lower() + '.py'
    filepath = os.path.join(_APP_DIR, 'modules', filename)
    if os.path.exists(filepath):
        print(f"Error: {filepath} already exists.")
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
    print(f"Controller created at: {filepath}")


def make_model(name):
    filename = name.lower() + '.py'
    filepath = os.path.join(_APP_DIR, 'models', filename)
    if os.path.exists(filepath):
        print(f"Error: {filepath} already exists.")
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
    print(f"Model {name} created at: {filepath}")
    print(f"Don't forget to register the model in {_APP_DIR}/models/__init__.py")


def migrate_init():
    """Initialize Aerich migration system."""
    print("Initializing Aerich migrations...")
    subprocess.run(
        [sys.executable, '-m', 'aerich', 'init', '-t', 'settings.TORTOISE_ORM'],
        cwd=_APP_DIR,
    )
    subprocess.run(
        [sys.executable, '-m', 'aerich', 'init-db'],
        cwd=_APP_DIR,
    )


def migrate_make(name: str, app: str = 'models'):
    """Create a new migration for the specified app."""
    print(f"Creating migration: {name} (app: {app})...")
    subprocess.run(
        [sys.executable, '-m', 'aerich', '--app', app, 'migrate', '--name', name],
        cwd=_APP_DIR,
    )


def migrate_upgrade(app: str | None = None):
    """Run pending migrations. If app is None, upgrade all apps."""
    apps = [app] if app else ['framework', 'models']
    for a in apps:
        print(f"Running migrations (upgrade) for app: {a}...")
        subprocess.run(
            [sys.executable, '-m', 'aerich', '--app', a, 'upgrade'],
            cwd=_APP_DIR,
        )


def migrate_downgrade(steps: int = 1, delete: bool = False, app: str = 'models'):
    """Rollback migrations for the specified app."""
    print(f"Rolling back {steps} migration(s) for app: {app}...")
    cmd = [sys.executable, '-m', 'aerich', '--app', app, 'downgrade', '-v', str(steps)]
    if delete:
        cmd.append('-d')
    subprocess.run(cmd, cwd=_APP_DIR)


def db_seed():
    """Run database seeders."""
    print("Running database seeders...")
    script = (
        "import asyncio, sys, os\n"
        "sys.path.insert(0, '.')\n"
        "import settings\n"
        "from core.conf import configure; configure(settings)\n"
        "import models\n"
        "from tortoise import Tortoise\n"
        "async def _seed():\n"
        "    await Tortoise.init(config=settings.TORTOISE_ORM)\n"
        "    from seeders.database_seeder import run\n"
        "    await run()\n"
        "    await Tortoise.close_connections()\n"
        "asyncio.run(_seed())\n"
    )
    subprocess.run([sys.executable, '-c', script], cwd=_APP_DIR)


def queue_work(name):
    """Run the queue worker."""
    print(f"Starting queue worker for: {name}...")
    script = (
        "import asyncio, sys\n"
        "sys.path.insert(0, '.')\n"
        "import settings\n"
        "from core.conf import configure; configure(settings)\n"
        "import models\n"
        "from tortoise import Tortoise\n"
        "from core.queue_worker import work\n"
        "async def run_worker():\n"
        "    await Tortoise.init(config=settings.TORTOISE_ORM)\n"
        f"    await work(queue_name='{name}')\n"
        "asyncio.run(run_worker())\n"
    )
    try:
        subprocess.run([sys.executable, '-c', script], cwd=_APP_DIR)
    except KeyboardInterrupt:
        pass


def make_seeder(name):
    """Generate a seeder boilerplate."""
    filename = name.lower() + '_seeder.py'
    filepath = os.path.join(_APP_DIR, 'seeders', filename)
    if os.path.exists(filepath):
        print(f"Error: {filepath} already exists.")
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
    print(f"Seeder created at: {filepath}")
    print(f"Don't forget to register it in seeders/database_seeder.py")


_GITLAB_PROJECT = 'sembeimexico%2Fnori'  # URL-encoded GitLab project path
_GITLAB_URL = 'https://gitlab.com'
_CORE_DIR = os.path.join(_APP_DIR, 'core')
_FRAMEWORK_MODELS_DIR = os.path.join(_APP_DIR, 'models', 'framework')
_FRAMEWORK_MIGRATIONS_DIR = os.path.join(_APP_DIR, 'migrations', 'framework')
_BACKUP_DIR = os.path.join('rootsystem', '.framework_backups')

# Directories owned by the framework — synced on update
_FRAMEWORK_DIRS = {
    'rootsystem/application/core/': _CORE_DIR,
    'rootsystem/application/models/framework/': _FRAMEWORK_MODELS_DIR,
    'rootsystem/application/migrations/framework/': _FRAMEWORK_MIGRATIONS_DIR,
}


def _get_current_version() -> str:
    """Read the current framework version from core/version.py."""
    version_file = os.path.join(_CORE_DIR, 'version.py')
    if not os.path.exists(version_file):
        return 'unknown'
    with open(version_file) as f:
        for line in f:
            if line.startswith('__version__'):
                return line.split('=')[1].strip().strip("'\"")
    return 'unknown'


def _gitlab_api(endpoint: str) -> dict | list:
    """Make a GET request to the GitLab API."""
    url = f'{_GITLAB_URL}/api/v4/projects/{_GITLAB_PROJECT}/{endpoint}'
    req = Request(url, headers={'User-Agent': 'Nori-Framework-Updater'})
    token = os.environ.get('GITLAB_TOKEN', '')
    if token:
        req.add_header('PRIVATE-TOKEN', token)
    with urlopen(req) as resp:
        return json.loads(resp.read())


def _download_zip(url: str, dest: str) -> None:
    """Download a file from a URL to a local path."""
    req = Request(url, headers={'User-Agent': 'Nori-Framework-Updater'})
    token = os.environ.get('GITLAB_TOKEN', '')
    if token:
        req.add_header('PRIVATE-TOKEN', token)
    with urlopen(req) as resp, open(dest, 'wb') as f:
        shutil.copyfileobj(resp, f)


def framework_update(target_version: str | None = None, skip_backup: bool = False, force: bool = False):
    """Update the framework core from a GitLab release.

    Downloads the release zip, extracts framework directories, backs up
    the current ones, and replaces them with the new version.
    """
    current = _get_current_version()
    print(f"Nori framework:update")
    print(f"  Current version: {current}")

    # 1. Resolve target version via GitLab Releases API
    try:
        if target_version:
            release = _gitlab_api(f'releases/v{target_version}')
        else:
            releases = _gitlab_api('releases?per_page=1')
            if not releases:
                print(f"\n  Error: No releases found.")
                print(f"  Check {_GITLAB_URL}/sembeimexico/nori/-/releases")
                return
            release = releases[0]
    except HTTPError as e:
        if e.code == 404:
            print(f"\n  Error: {'Version v' + target_version + ' not found' if target_version else 'No releases found'}.")
            print(f"  Check {_GITLAB_URL}/sembeimexico/nori/-/releases")
            return
        raise
    except URLError as e:
        print(f"\n  Error: Could not connect to GitLab — {e.reason}")
        print("  Check your internet connection or set GITLAB_TOKEN for private repos.")
        return

    tag = release['tag_name']
    version = tag.lstrip('v')
    print(f"  Target version:  {version} ({tag})")

    if version == current and not force:
        print(f"\n  Already up to date. Use --force to re-install.")
        return

    # 2. Download the release zip (GitLab archive endpoint)
    zip_url = f'{_GITLAB_URL}/api/v4/projects/{_GITLAB_PROJECT}/repository/archive.zip?sha={tag}'
    print(f"\n  Downloading {tag}...")

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = os.path.join(tmp, 'release.zip')
        try:
            _download_zip(zip_url, zip_path)
        except (URLError, HTTPError) as e:
            print(f"  Error: Download failed — {e}")
            return

        # 3. Extract framework directories from the zip
        with zipfile.ZipFile(zip_path) as zf:
            # GitHub zips have a root folder like "owner-repo-sha/"
            root_prefix = zf.namelist()[0].split('/')[0] + '/'

            # Locate each framework directory in the zip
            extracted: dict[str, str] = {}
            for zip_rel_path, local_dir in _FRAMEWORK_DIRS.items():
                full_prefix = root_prefix + zip_rel_path
                extract_dir = os.path.join(tmp, zip_rel_path.replace('/', '_'))
                found = False
                for member in zf.namelist():
                    if member.startswith(full_prefix) and not member.endswith('/'):
                        found = True
                        relative_path = member[len(full_prefix):]
                        dest_path = os.path.join(extract_dir, relative_path)
                        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                        with zf.open(member) as src, open(dest_path, 'wb') as dst:
                            shutil.copyfileobj(src, dst)
                if found:
                    extracted[local_dir] = extract_dir

            if _CORE_DIR not in extracted:
                print("  Error: Release zip does not contain rootsystem/application/core/")
                print("  This release may not be compatible with your project structure.")
                return

        # 4. Backup current framework directories
        if not skip_backup:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_root = os.path.join(_BACKUP_DIR, f'v{current}_{timestamp}')
            os.makedirs(backup_root, exist_ok=True)
            for local_dir in extracted:
                if os.path.exists(local_dir):
                    rel_path = os.path.relpath(local_dir, _APP_DIR)
                    backup_dest = os.path.join(backup_root, rel_path)
                    print(f"  Backing up {local_dir} → {backup_dest}")
                    os.makedirs(os.path.dirname(backup_dest), exist_ok=True)
                    shutil.copytree(local_dir, backup_dest)

        # 5. Replace framework directories
        for local_dir, extract_dir in extracted.items():
            label = os.path.relpath(local_dir, _APP_DIR)
            print(f"  Replacing {label}/ ...")
            if os.path.exists(local_dir):
                shutil.rmtree(local_dir)
            shutil.copytree(extract_dir, local_dir)

    print(f"\n  Updated: {current} → {version}")
    has_migrations = _FRAMEWORK_MIGRATIONS_DIR in extracted
    if has_migrations:
        print(f"  New framework migrations detected.")
        print(f"  Run: python3 nori.py migrate:upgrade --app framework")


def framework_version():
    """Show the current framework version."""
    print(f"Nori v{_get_current_version()}")


def main():
    parser = argparse.ArgumentParser(description="Nori CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: serve
    serve_parser = subparsers.add_parser("serve", help="Start the dev server with hot reload")
    serve_parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    serve_parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")

    # Command: make:controller
    parser_controller = subparsers.add_parser("make:controller", help="Create a new controller")
    parser_controller.add_argument("name", type=str, help="Entity name (e.g. Product)")

    # Command: make:model
    parser_model = subparsers.add_parser("make:model", help="Create a new Tortoise ORM model")
    parser_model.add_argument("name", type=str, help="Entity name (e.g. Product)")

    # Command: make:seeder
    parser_seeder = subparsers.add_parser("make:seeder", help="Create a new database seeder")
    parser_seeder.add_argument("name", type=str, help="Entity name (e.g. User)")

    # Command: migrate:init
    subparsers.add_parser("migrate:init", help="Initialize Aerich migration system")

    # Command: migrate:make
    p_migrate = subparsers.add_parser("migrate:make", help="Create a new migration")
    p_migrate.add_argument("name", type=str, help="Migration name (e.g. add_users_table)")
    p_migrate.add_argument("--app", default="models", help="App label: models (default) or framework")

    # Command: migrate:upgrade
    p_upgrade = subparsers.add_parser("migrate:upgrade", help="Run pending migrations")
    p_upgrade.add_argument("--app", default=None, help="App label: models, framework, or omit for both")

    # Command: migrate:downgrade
    p_down = subparsers.add_parser("migrate:downgrade", help="Rollback migrations")
    p_down.add_argument("--steps", type=int, default=1, help="Number of migrations to roll back")
    p_down.add_argument("--delete", action="store_true", help="Delete migration files on downgrade")
    p_down.add_argument("--app", default="models", help="App label: models (default) or framework")

    # Command: db:seed
    subparsers.add_parser("db:seed", help="Run database seeders")

    # Command: queue:work
    parser_work = subparsers.add_parser("queue:work", help="Run the queue worker")
    parser_work.add_argument("--name", default="default", help="Queue name")

    # Command: framework:update
    parser_update = subparsers.add_parser("framework:update", help="Update the Nori core from GitHub")
    parser_update.add_argument("--version", default=None, help="Target version (e.g. 1.3.0). Defaults to latest.")
    parser_update.add_argument("--no-backup", action="store_true", help="Skip backing up the current core/")
    parser_update.add_argument("--force", action="store_true", help="Re-install even if already on the target version")

    # Command: framework:version
    subparsers.add_parser("framework:version", help="Show the current framework version")

    args = parser.parse_args()

    if args.command == "serve":
        serve(host=args.host, port=args.port)
    elif args.command == "make:controller":
        make_controller(args.name)
    elif args.command == "make:model":
        make_model(args.name)
    elif args.command == "make:seeder":
        make_seeder(args.name)
    elif args.command == "migrate:init":
        migrate_init()
    elif args.command == "migrate:make":
        migrate_make(args.name, app=args.app)
    elif args.command == "migrate:upgrade":
        migrate_upgrade(app=args.app)
    elif args.command == "migrate:downgrade":
        migrate_downgrade(steps=args.steps, delete=args.delete, app=args.app)
    elif args.command == "db:seed":
        db_seed()
    elif args.command == "queue:work":
        queue_work(args.name)
    elif args.command == "framework:update":
        framework_update(target_version=args.version, skip_backup=args.no_backup, force=args.force)
    elif args.command == "framework:version":
        framework_version()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
