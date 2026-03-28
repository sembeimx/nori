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


def migrate_make(name):
    """Create a new migration."""
    print(f"Creating migration: {name}...")
    subprocess.run(
        [sys.executable, '-m', 'aerich', 'migrate', '--name', name],
        cwd=_APP_DIR,
    )


def migrate_upgrade():
    """Run pending migrations."""
    print("Running migrations (upgrade)...")
    subprocess.run(
        [sys.executable, '-m', 'aerich', 'upgrade'],
        cwd=_APP_DIR,
    )


def migrate_downgrade(steps=1, delete=False):
    """Rollback migrations."""
    print(f"Rolling back {steps} migration(s)...")
    cmd = [sys.executable, '-m', 'aerich', 'downgrade', '-v', str(steps)]
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


_GITHUB_REPO = 'ellery-nori/nori'  # GitHub owner/repo for framework releases
_CORE_DIR = os.path.join(_APP_DIR, 'core')
_BACKUP_DIR = os.path.join('rootsystem', '.core_backups')


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


def _github_api(endpoint: str) -> dict:
    """Make a GET request to the GitHub API."""
    url = f'https://api.github.com/repos/{_GITHUB_REPO}/{endpoint}'
    req = Request(url, headers={
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'Nori-Framework-Updater',
    })
    token = os.environ.get('GITHUB_TOKEN', '')
    if token:
        req.add_header('Authorization', f'Bearer {token}')
    with urlopen(req) as resp:
        return json.loads(resp.read())


def _download_zip(url: str, dest: str) -> None:
    """Download a file from a URL to a local path."""
    req = Request(url, headers={'User-Agent': 'Nori-Framework-Updater'})
    token = os.environ.get('GITHUB_TOKEN', '')
    if token:
        req.add_header('Authorization', f'Bearer {token}')
    with urlopen(req) as resp, open(dest, 'wb') as f:
        shutil.copyfileobj(resp, f)


def framework_update(target_version: str | None = None, skip_backup: bool = False):
    """Update the framework core from a GitHub release.

    Downloads the release zip, extracts core/ from it, backs up the
    current core/, and replaces it with the new version.
    """
    current = _get_current_version()
    print(f"Nori framework:update")
    print(f"  Current version: {current}")

    # 1. Resolve target version
    try:
        if target_version:
            release = _github_api(f'releases/tags/v{target_version}')
        else:
            release = _github_api('releases/latest')
    except HTTPError as e:
        if e.code == 404:
            print(f"\n  Error: {'Version v' + target_version + ' not found' if target_version else 'No releases found'}.")
            print(f"  Check https://github.com/{_GITHUB_REPO}/releases")
            return
        raise
    except URLError as e:
        print(f"\n  Error: Could not connect to GitHub — {e.reason}")
        print("  Check your internet connection or set GITHUB_TOKEN for private repos.")
        return

    tag = release['tag_name']
    version = tag.lstrip('v')
    print(f"  Target version:  {version} ({tag})")

    if version == current:
        print(f"\n  Already up to date.")
        return

    # 2. Download the release zip
    zip_url = release['zipball_url']
    print(f"\n  Downloading {tag}...")

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = os.path.join(tmp, 'release.zip')
        try:
            _download_zip(zip_url, zip_path)
        except (URLError, HTTPError) as e:
            print(f"  Error: Download failed — {e}")
            return

        # 3. Extract and locate core/ in the zip
        with zipfile.ZipFile(zip_path) as zf:
            # GitHub zips have a root folder like "owner-repo-sha/"
            root_prefix = zf.namelist()[0].split('/')[0] + '/'
            core_prefix = None
            for name in zf.namelist():
                relative = name[len(root_prefix):]
                if relative.startswith('rootsystem/application/core/'):
                    core_prefix = root_prefix + 'rootsystem/application/core/'
                    break

            if not core_prefix:
                print("  Error: Release zip does not contain rootsystem/application/core/")
                print("  This release may not be compatible with your project structure.")
                return

            # Extract core/ to a temp location
            extract_dir = os.path.join(tmp, 'extracted_core')
            for member in zf.namelist():
                if member.startswith(core_prefix) and not member.endswith('/'):
                    relative_path = member[len(core_prefix):]
                    dest_path = os.path.join(extract_dir, relative_path)
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    with zf.open(member) as src, open(dest_path, 'wb') as dst:
                        shutil.copyfileobj(src, dst)

        # 4. Backup current core/
        if not skip_backup:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_name = f'core_{current}_{timestamp}'
            backup_path = os.path.join(_BACKUP_DIR, backup_name)
            os.makedirs(_BACKUP_DIR, exist_ok=True)
            print(f"  Backing up current core/ → {backup_path}")
            shutil.copytree(_CORE_DIR, backup_path)

        # 5. Replace core/
        print(f"  Replacing core/ with {tag}...")
        shutil.rmtree(_CORE_DIR)
        shutil.copytree(extract_dir, _CORE_DIR)

    print(f"\n  Updated: {current} → {version}")
    print(f"  Run 'python3 nori.py migrate:upgrade' if the new version includes migration changes.")


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

    # Command: migrate:upgrade
    subparsers.add_parser("migrate:upgrade", help="Run pending migrations")

    # Command: migrate:downgrade
    p_down = subparsers.add_parser("migrate:downgrade", help="Rollback migrations")
    p_down.add_argument("--steps", type=int, default=1, help="Number of migrations to roll back")
    p_down.add_argument("--delete", action="store_true", help="Delete migration files on downgrade")

    # Command: db:seed
    subparsers.add_parser("db:seed", help="Run database seeders")

    # Command: queue:work
    parser_work = subparsers.add_parser("queue:work", help="Run the queue worker")
    parser_work.add_argument("--name", default="default", help="Queue name")

    # Command: framework:update
    parser_update = subparsers.add_parser("framework:update", help="Update the Nori core from GitHub")
    parser_update.add_argument("--version", default=None, help="Target version (e.g. 1.3.0). Defaults to latest.")
    parser_update.add_argument("--no-backup", action="store_true", help="Skip backing up the current core/")

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
        migrate_make(args.name)
    elif args.command == "migrate:upgrade":
        migrate_upgrade()
    elif args.command == "migrate:downgrade":
        migrate_downgrade(steps=args.steps, delete=args.delete)
    elif args.command == "db:seed":
        db_seed()
    elif args.command == "queue:work":
        queue_work(args.name)
    elif args.command == "framework:update":
        framework_update(target_version=args.version, skip_backup=args.no_backup)
    elif args.command == "framework:version":
        framework_version()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
