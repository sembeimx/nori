# Nori CLI

The Nori CLI (`nori.py`) is the primary tool for development workflows — scaffolding code, managing database migrations, seeding data, and running the dev server.

Commands use colon-separated naming (`make:model`, `migrate:upgrade`) because they group naturally in your head. Type `make:` and you know what's coming. Type `migrate:` and the scope is clear. It's namespace-like without being verbose.

```bash
python3 nori.py <command> [arguments]
```

---

## Command Reference

| Command | Description |
|---------|-------------|
| `serve` | Start the development server with hot reload |
| `make:controller <Name>` | Generate a controller skeleton in `modules/` |
| `make:model <Name>` | Generate a Tortoise ORM model in `models/` |
| `make:seeder <Name>` | Generate a database seeder in `seeders/` |
| `migrate:init` | Initialize the Aerich migration system |
| `migrate:make <name>` | Create a new migration from model changes |
| `migrate:upgrade` | Apply all pending migrations (both apps) |
| `migrate:downgrade` | Roll back last migration |
| `migrate:fix` | Fix migration files to current Aerich format |
| `migrate:fresh` | Drop DB + delete migrations + re-init (dev only) |
| `db:seed` | Run all registered database seeders |
| `queue:work` | Run the persistent job queue worker |
| `framework:update` | Update the Nori core from GitHub |
| `framework:version` | Show the current framework version |
| `routes:list` | List all registered routes |
| `audit:purge` | Purge old audit log entries |

---

## Development Server

```bash
python3 nori.py serve
python3 nori.py serve --host 127.0.0.1 --port 3000
```

Starts Uvicorn with hot reload enabled. Watches both Python files and the `rootsystem/templates/` directory for changes — editing a template triggers a reload automatically.

| Flag | Default | Description |
|------|---------|-------------|
| `--host` | `0.0.0.0` | Bind address |
| `--port` | `8000` | Port number |

---

## Route Inspection

```bash
python3 nori.py routes:list
```

Prints a table of all registered routes from `routes.py`, including path, HTTP methods, and route name:

```
  Path       Methods  Name
  ---------  -------  ------------
  /health    GET      health.check
  /          GET      page.home
  /ws/echo   WS       ws.echo

  3 route(s) registered.
```

`Mount` groups are expanded — nested routes show their full prefix. WebSocket routes display `WS` in the methods column.

---

## Code Generators

All generators follow the same pattern: they create a single file with working boilerplate that you customize. If the target file already exists, the command exits with an error to prevent overwriting your work.

### `make:controller`

```bash
python3 nori.py make:controller Product
```

Creates `rootsystem/application/modules/product.py`:

```python
from starlette.requests import Request
from starlette.responses import JSONResponse
from core.jinja import templates


class ProductController:

    async def list(self, request: Request):
        return JSONResponse({"message": "Product List"})

    async def create(self, request: Request):
        pass
```

**After generating**, you must:

1. Add your business logic to the controller methods.
2. Register routes in `rootsystem/application/routes.py`:

```python
from modules.product import ProductController

product = ProductController()

routes = [
    # ...existing routes...
    Mount('/products', routes=[
        Route('/', product.list, methods=['GET'], name='products.index'),
        Route('/', product.create, methods=['POST'], name='products.store'),
    ]),
]
```

Controllers are plain Python classes — no base class, no magic. Methods are async callables that receive `(self, request)` and return a Starlette `Response`.

### `make:model`

```bash
python3 nori.py make:model Product
```

Creates `rootsystem/application/models/product.py`:

```python
from tortoise.models import Model
from tortoise import fields
from core.mixins.model import NoriModelMixin


class Product(NoriModelMixin, Model):
    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=100)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = 'products'
```

**After generating**, you must:

1. Edit the model to add your fields (see [Tortoise ORM field reference](https://tortoise.github.io/fields.html)).
2. **Register the model** in `rootsystem/application/models/__init__.py`:

```python
from models.product import Product
```

Without this registration, Tortoise ORM will not discover the model, and migrations will fail silently.

3. Create and run a migration:

```bash
python3 nori.py migrate:make add_products_table
python3 nori.py migrate:upgrade
```

**Tip**: If a model has sensitive fields, add `protected_fields` to prevent leaks via `to_dict()`:

```python
class User(NoriModelMixin, Model):
    protected_fields = ['password_hash', 'remember_token']
    # ...fields...
```

### `make:seeder`

```bash
python3 nori.py make:seeder Product
```

Creates `rootsystem/application/seeders/product_seeder.py`:

```python
"""Seeder for Product."""
# from models.product import Product


async def run() -> None:
    """Seed Product data."""
    # await Product.create(name='Example')
    pass
```

**After generating**, you must:

1. Uncomment the model import and add your seed data.
2. Register the seeder in `rootsystem/application/seeders/database_seeder.py`:

```python
SEEDERS: list[str] = [
    'seeders.product_seeder',
]
```

3. Run it:

```bash
python3 nori.py db:seed
```

---

## Framework Management

Nori 1.2+ includes commands to manage the framework core independently of your application code.

### `framework:update`

Updates all framework-owned directories by downloading the latest release from the official GitHub repository.

```bash
python3 nori.py framework:update
python3 nori.py framework:update --version 1.3.0
python3 nori.py framework:update --no-backup
```

**Options**:
- `--version <v>`: Update to a specific version (e.g. `1.3.0`). Defaults to latest release.
- `--no-backup`: Skip the automatic backup (useful for CI/Docker).
- `--force`: Re-install even if already on the target version.

**What gets updated**:

| Directory | Contents |
|-----------|----------|
| `core/` | Framework core (auth, cache, mail, queue, etc.) |
| `models/framework/` | Framework models (AuditLog, Job, Permission, Role) |
| `migrations/framework/` | Framework migration files |

**Process**:
1. Reads current version from `core/version.py`.
2. Queries the GitHub Releases API for the target version.
3. Creates a timestamped backup in `rootsystem/.framework_backups/`.
4. Downloads and extracts the release zip.
5. Replaces all three framework directories.
6. If new framework migrations are detected, prompts to run `migrate:upgrade --app framework`.

For private repositories, set `GITHUB_TOKEN` in your environment.

### `framework:version`

Displays the current version of the Nori core installed in the project.

```bash
python3 nori.py framework:version
# Nori v1.2.0
```

### Audit Log

Purge old entries from the `audit_logs` table. Useful for keeping the database lean in production.

```bash
# Preview how many entries would be purged
python3 nori.py audit:purge --days 90 --dry-run

# Export to CSV and purge
python3 nori.py audit:purge --days 90 --export

# Purge directly (no export)
python3 nori.py audit:purge --days 90
```

| Flag | Default | Description |
|------|---------|-------------|
| `--days` | `90` | Delete entries older than N days |
| `--export` | off | Export matching entries to CSV before deleting |
| `--dry-run` | off | Show count without deleting |

Recommended cron for production:

```
# Every Sunday at 3am, purge entries older than 90 days
0 3 * * 0 cd /path/to/app && python3 nori.py audit:purge --days 90
```

---

## Database Seeding

The seeder system lets you populate your database with test/initial data in a repeatable way.

### How It Works

1. `python3 nori.py db:seed` initializes a Tortoise ORM connection and calls `seeders/database_seeder.py:run()`.
2. `database_seeder.py` iterates through the `SEEDERS` list and dynamically imports each module.
3. Each seeder module must define an `async def run() -> None` function.
4. Seeders execute **in order** — put dependencies first (e.g. `user_seeder` before `article_seeder`).

### Writing a Seeder

A seeder is a Python module with a single async function:

```python
"""Seeder for User."""
from models.user import User
from core.auth.security import Security


async def run() -> None:
    """Create initial users."""
    # Check if data already exists (idempotent seeding)
    if await User.filter(email='admin@example.com').exists():
        return

    await User.create(
        name='Admin',
        email='admin@example.com',
        password=Security.hash_password('password'),
        role='admin',
    )

    await User.create(
        name='Editor',
        email='editor@example.com',
        password=Security.hash_password('password'),
        role='editor',
    )
```

### Seeder Registration

All seeders must be registered in `seeders/database_seeder.py` using dot-notation module paths:

```python
SEEDERS: list[str] = [
    'seeders.role_seeder',        # Create roles first
    'seeders.user_seeder',        # Then users (may reference roles)
    'seeders.category_seeder',    # Then categories
    'seeders.article_seeder',     # Then articles (may reference categories + users)
]
```

Order matters — if `article_seeder` creates articles that belong to a user, `user_seeder` must run first.

### Error Handling

If a seeder raises an exception, the error is logged with full traceback and execution stops. Seeders that ran before the failure are **not rolled back** — use idempotent checks (`if await Model.exists()`) to make seeders safe to re-run.

---

## Migrations

Nori uses **Aerich** (async migration tool for Tortoise ORM) wrapped in convenient CLI commands.

### First-Time Setup

```bash
python3 nori.py migrate:init
```

This does two things:
1. Initializes Aerich configuration (reads `settings.TORTOISE_ORM`)
2. Creates the initial database schema from your current models

### Creating Migrations

After modifying a model (adding fields, changing types, etc.):

```bash
python3 nori.py migrate:make add_price_to_products
python3 nori.py migrate:make add_price_to_products --app models     # same (default)
python3 nori.py migrate:make add_audit_field --app framework        # framework models only
```

This compares your models against the last migration state and generates a migration file in `migrations/models/` (or `migrations/framework/` for framework models).

**Naming convention**: use descriptive names like `add_price_to_products`, `create_orders_table`, `remove_legacy_status_field`.

### Applying Migrations

```bash
python3 nori.py migrate:upgrade                   # Both apps (framework + models)
python3 nori.py migrate:upgrade --app models       # User models only
python3 nori.py migrate:upgrade --app framework    # Framework models only
```

When `--app` is omitted, both `framework` and `models` are upgraded in order.

### Migration Directory Structure

Nori uses two separate migration namespaces:

```
migrations/
├── framework/    ← Managed by Nori (ships with framework:update)
└── models/       ← Managed by the developer (your models)
```

Framework migrations are never mixed with your application migrations. When you run `framework:update`, new framework migrations are downloaded automatically and can be applied with `migrate:upgrade --app framework`.

### Rolling Back

```bash
python3 nori.py migrate:downgrade                          # Roll back 1 (user models)
python3 nori.py migrate:downgrade --steps 3                # Roll back 3
python3 nori.py migrate:downgrade --app framework          # Roll back framework
python3 nori.py migrate:downgrade --delete                 # Roll back and delete the file
```

---

## Extending the CLI

The CLI uses Python's `argparse` with a plugin system based on the `commands/` directory. The entry point `nori.py` is a thin bootstrap — all framework command logic lives in `core/cli.py`, which updates automatically with `framework:update`. Your custom commands live in `commands/` and are never touched by updates.

### Adding a Custom Command

Create a Python file in `rootsystem/application/commands/`. Each file must export two functions:

- `register(subparsers)` — adds one or more argparse subparsers
- `handle(args)` — executes the command when invoked

**Example** — `commands/stats.py`:

```python
"""Show application statistics."""
from __future__ import annotations

import subprocess
import sys


def register(subparsers) -> None:
    parser = subparsers.add_parser('app:stats', help='Show application statistics')
    parser.add_argument('--verbose', action='store_true', help='Show detailed stats')


def handle(args) -> None:
    print("Application Stats")
    print("=" * 40)
    if args.verbose:
        print("  Verbose mode enabled")
    # Your logic here
```

Then run it:

```bash
python3 nori.py app:stats
python3 nori.py app:stats --verbose
```

An example file is provided at `commands/_example.py` — rename it (remove the `_` prefix) to activate.

### How It Works

1. The CLI scans `commands/*.py` at startup (files starting with `_` are skipped)
2. Each module's `register(subparsers)` is called to add its command(s)
3. When the command is invoked, the module's `handle(args)` receives the parsed args
4. If a module fails to load, a warning is printed and the CLI continues

### Command Naming Convention

Follow the `category:action` pattern:

- `make:*` — Code generation commands
- `migrate:*` — Database migration commands
- `db:*` — Database utility commands
- `queue:*` — Queue management
- `app:*` — Application-specific commands (recommended for user commands)

### Running Async Code in Custom Commands

If your command needs database access or async operations, use the subprocess pattern to get a dedicated Tortoise connection:

```python
import subprocess
import sys

def register(subparsers) -> None:
    subparsers.add_parser('app:count-users', help='Count all users')


def handle(args) -> None:
    script = (
        "import asyncio, sys\n"
        "sys.path.insert(0, '.')\n"
        "import settings\n"
        "from tortoise import Tortoise\n"
        "async def _run():\n"
        "    await Tortoise.init(config=settings.TORTOISE_ORM)\n"
        "    from models.user import User\n"
        "    count = await User.all().count()\n"
        "    print(f'Total users: {count}')\n"
        "    await Tortoise.close_connections()\n"
        "asyncio.run(_run())\n"
    )
    subprocess.run([sys.executable, '-c', script], cwd='.')
```

This spawns a subprocess with its own Tortoise connection, keeping the CLI process lightweight.

---

## Complete Workflow Example

Creating a blog feature from scratch:

```bash
# 1. Generate model and controller
python3 nori.py make:model Article
python3 nori.py make:controller Article

# 2. Edit the model — add fields
#    rootsystem/application/models/article.py

# 3. Register the model
#    rootsystem/application/models/__init__.py
#    Add: from models.article import Article

# 4. Create and run migration
python3 nori.py migrate:make create_articles_table
python3 nori.py migrate:upgrade

# 5. Edit the controller — add logic
#    rootsystem/application/modules/article.py

# 6. Register routes
#    rootsystem/application/routes.py

# 7. Create seeder for test data
python3 nori.py make:seeder Article
#    Edit rootsystem/application/seeders/article_seeder.py
#    Register in seeders/database_seeder.py

# 8. Seed the database
python3 nori.py db:seed

# 9. Start developing
python3 nori.py serve
```
