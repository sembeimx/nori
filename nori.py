#!/usr/bin/env python3
import sys
import os
import subprocess
import argparse

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
    id = fields.IntField(pk=True)
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
        "from tortoise import Tortoise\n"
        "async def _seed():\n"
        "    await Tortoise.init(config=settings.TORTOISE_ORM)\n"
        "    await Tortoise.generate_schemas()\n"
        "    from seeders.database_seeder import run\n"
        "    await run()\n"
        "    await Tortoise.close_connections()\n"
        "asyncio.run(_seed())\n"
    )
    subprocess.run([sys.executable, '-c', script], cwd=_APP_DIR)


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
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
