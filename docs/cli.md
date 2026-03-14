# Nori CLI

The Nori CLI (`nori.py`) is the primary tool for development workflows — scaffolding code, managing database migrations, seeding data, and running the dev server. It follows **Laravel Artisan-style naming** with colon-separated commands.

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
| `migrate:upgrade` | Apply all pending migrations |
| `migrate:downgrade` | Roll back migrations |
| `db:seed` | Run all registered database seeders |

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
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=100)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = 'product'
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
```

This compares your models against the last migration state and generates a migration file in `rootsystem/application/migrations/`.

**Naming convention**: use descriptive names like `add_price_to_products`, `create_orders_table`, `remove_legacy_status_field`.

### Applying Migrations

```bash
python3 nori.py migrate:upgrade
```

Applies all pending migrations in order.

### Rolling Back

```bash
python3 nori.py migrate:downgrade              # Roll back 1 migration
python3 nori.py migrate:downgrade --steps 3     # Roll back 3 migrations
python3 nori.py migrate:downgrade --delete      # Roll back and delete the migration file
```

---

## Extending the CLI

The CLI is intentionally simple — a single `nori.py` file using Python's `argparse`. There is no plugin system by design (consistent with "Keep it Native").

### Adding a Custom Command

To add your own command, edit `nori.py`:

**Step 1** — Add a handler function:

```python
def my_custom_command(arg1):
    """Description of what it does."""
    print(f"Running custom command with {arg1}")
    # Your logic here — import modules, run scripts, etc.
```

**Step 2** — Register the subparser (in `main()`):

```python
# Command: custom:task
parser_custom = subparsers.add_parser("custom:task", help="Run my custom task")
parser_custom.add_argument("arg1", type=str, help="First argument")
```

**Step 3** — Add the dispatch condition (in `main()`):

```python
elif args.command == "custom:task":
    my_custom_command(args.arg1)
```

### Command Naming Convention

Follow the `category:action` pattern:

- `make:*` — Code generation commands
- `migrate:*` — Database migration commands
- `db:*` — Database utility commands
- `queue:*` — Queue management (planned)
- `cache:clear` — Cache management (example)

### Running Async Code in Custom Commands

If your command needs database access or async operations, use the same pattern as `db:seed`:

```python
def my_async_command():
    """Run an async operation with database access."""
    script = (
        "import asyncio, sys\n"
        "sys.path.insert(0, '.')\n"
        "import settings\n"
        "from tortoise import Tortoise\n"
        "async def _run():\n"
        "    await Tortoise.init(config=settings.TORTOISE_ORM)\n"
        "    # Your async logic here\n"
        "    from models.user import User\n"
        "    count = await User.all().count()\n"
        "    print(f'Total users: {count}')\n"
        "    await Tortoise.close_connections()\n"
        "asyncio.run(_run())\n"
    )
    subprocess.run([sys.executable, '-c', script], cwd=_APP_DIR)
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
