# Database (Tortoise ORM)

In Nori, asynchronous database mapping (ORM) is handled by **Tortoise ORM** — a fully async ORM for Python (`async/await` native).

We chose Tortoise because it's async from the ground up — not an async wrapper around synchronous code. In an async framework, the ORM shouldn't be the bottleneck that blocks the event loop.

## Connection and Configuration

The engines (MySQL, PostgreSQL, SQLite) are defined in the `.env` file. The framework parses the requested engine in the central configuration file `rootsystem/application/settings.py`.

Make sure to document and register your Models inside `settings.py` (in the `TORTOISE_ORM['apps']['models']['models']` dictionary) so that Tortoise locates them immediately and allows inter-relationships.

## Defining a Model

Models are located in the `rootsystem/application/models/` directory. They must inherit from `NoriModelMixin` and `Model`. Class names are `PascalCase`; table names are **plural** (e.g., class `User` → table `users`).

```python
from __future__ import annotations

from tortoise.models import Model
from tortoise import fields
from core.mixins.model import NoriModelMixin

class User(NoriModelMixin, Model):
    protected_fields = ['password_hash', 'remember_token']  # Excluded from to_dict()

    id = fields.IntField(primary_key=True)
    slug = fields.CharField(max_length=50, unique=True)
    name = fields.CharField(max_length=100)
    email = fields.CharField(max_length=255)
    password_hash = fields.CharField(max_length=255)
    remember_token = fields.CharField(max_length=255, default='')
    level = fields.IntField(default=0)
    status = fields.BooleanField(default=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = 'users'  # Always plural, explicitly specified
```

### Registering a Model

After creating a model, **import it** in `rootsystem/application/models/__init__.py` so Tortoise ORM discovers it for migrations and relationships:

```python
# models/__init__.py
from models.user import User  # ← add your model here
```

Forgetting this step causes silent migration failures — Aerich won't detect the new model.

### NoriModelMixin (`to_dict` + `protected_fields`)
Inheriting this mixin alongside `Model` adds the `.to_dict()` method and `protected_fields` security. It strips ORM metadata and resolves everything into JSON-serializable primitives.

```python
user = await User.get(id=1)

user.to_dict()
# → {'id': 1, 'slug': 'alice', 'name': 'Alice', 'email': '...', ...}
# password_hash and remember_token are auto-excluded via protected_fields

user.to_dict(exclude=['email'])
# → protected_fields AND explicit exclude are merged

user.to_dict(include_protected=True)
# → force-include for internal/admin operations
```

Always use `.to_dict()` when serializing models to JSON responses — this ensures `protected_fields` safety. See [Security — protected_fields](security.md#orm-protected_fields) for details.

## Queries, Insertion and Basic Modification

```python
# Create
new_user = await User.create(name='Ellery', slug='ellery-1')

# Update
user = await User.get(id=1)
user.name = 'Ellery Modified'
await user.save()

# Select and Filter
active_users = await User.filter(status=True).all()
first_match = await User.filter(slug='foo').first()

# Filtered selects and exclusions
above_level_5 = await User.filter(level__gt=5).all()
inactive = await User.exclude(status=True).all()
```

*(Refer to the official Tortoise ORM documentation for advanced behaviors like `Q()`, `F()`, prefetching or raw SQL).*

## Migrations (Aerich)

Nori uses [Aerich](https://github.com/tortoise/aerich) for database migrations. Aerich is Tortoise ORM's native migration tool and is already configured.

### First-time setup

```bash
python3 nori.py migrate:init
```

This initializes the migration system and creates the `migrations/` directory inside `rootsystem/application/`.

### Creating a migration

After modifying your models (adding fields, changing types, etc.):

```bash
python3 nori.py migrate:make add_email_to_users
```

This generates a migration file in `migrations/models/`.

### Running migrations

```bash
python3 nori.py migrate:upgrade
```

> **Important**: In production (`DEBUG=false`), Nori relies exclusively on Aerich migrations to manage the database schema. `generate_schemas()` is only called in development mode as a convenience. Always run `migrate:upgrade` before deploying or seeding in production.

### Rolling back

```bash
python3 nori.py migrate:downgrade          # roll back 1 migration
python3 nori.py migrate:downgrade --steps 3 # roll back 3 migrations
```

### Workflow summary

1. Edit your model in `models/`
2. Run `python3 nori.py migrate:make <description>`
3. Review the generated migration file
4. Run `python3 nori.py migrate:upgrade`
5. Commit the migration file to version control

---

## Database Seeding

Nori includes a seeder system for populating your database with test or default data.

### Creating a seeder

```bash
python3 nori.py make:seeder User
```

This creates `seeders/user_seeder.py` with a boilerplate `async def run()` function.

### Registering and running seeders

1. Edit your seeder to create records
2. Register it in `seeders/database_seeder.py` by adding the module path to the `SEEDERS` list
3. Run all seeders:

```bash
python3 nori.py db:seed
```

---

## Built-in Models

Nori ships with three models for audit logging and granular permissions (ACL). They are registered automatically in `models/__init__.py`.

### AuditLog (`models/audit_log.py`)

Tracks who did what and when. Entries are created via the fire-and-forget `audit()` function from `core.audit`.

| Field | Type | Description |
|-------|------|-------------|
| `user_id` | IntField (nullable) | The acting user. Not a FK — preserves logs if users are deleted |
| `action` | CharField | Action performed: `create`, `update`, `delete`, `login`, `logout`, or custom |
| `model_name` | CharField (nullable) | Model name (e.g. `Article`) |
| `record_id` | CharField (nullable) | The affected record ID |
| `changes` | JSONField (nullable) | Change diff: `{"field": {"before": ..., "after": ...}}` |
| `ip_address` | CharField (nullable) | Client IP (supports `X-Forwarded-For`) |
| `request_id` | CharField (nullable) | From `RequestIdMiddleware` for tracing |
| `created_at` | DatetimeField | Auto-set on creation |

### Permission (`models/permission.py`)

A granular permission using dot-notation convention (e.g. `articles.edit`, `users.delete`).

| Field | Type | Description |
|-------|------|-------------|
| `name` | CharField (unique) | Permission identifier, e.g. `reports.view` |
| `description` | CharField | Human-readable description |

### Role (`models/role.py`)

Groups permissions via a Many-to-Many relationship through the `role_permission` table.

| Field | Type | Description |
|-------|------|-------------|
| `name` | CharField (unique) | Role name, e.g. `editor` |
| `permissions` | M2M → Permission | Linked via `role_permission` join table |

---

## Advanced Native Mixins

Nori includes pre-built abstracted layers in the form of Python mixins for solving repetitive modern tasks.

These mixins exist because we've seen the same patterns in every project: soft deletes (you always regret a hard delete), tree structures (categories, permissions, org charts), and safe serialization (sensitive fields leaking into API responses). We built them once, correctly.

### NoriSoftDeletes (Logical Deletion)
Protects transactional entropy by preventing hard `DROP` or `DELETE` SQL operations. `NoriSoftDeletes` already inherits from Tortoise's `Model`, so you do **not** need to inherit from both — just replace `Model` with `NoriSoftDeletes`. The mixin adds a nullable `deleted_at` DatetimeField that is automatically set to the current timestamp when `.delete()` is called.

```python
from core.mixins.soft_deletes import NoriSoftDeletes
from core.mixins.model import NoriModelMixin

class Post(NoriModelMixin, NoriSoftDeletes):  # NoriSoftDeletes replaces Model
    title = fields.CharField(max_length=200)
```

**Managers:**
* `Post.objects` (default) — automatically excludes soft-deleted records from all queries.
* `Post.all_objects` — includes everything (active + deleted).
* `Post.trashed` — only soft-deleted records.

**Instance methods:**
* `await post.delete()` — sets `deleted_at` to `NOW()`. Queries via `objects` manager will exclude this record.
* `await post.restore()` — clears `deleted_at`, returning the record to the active filter. Idempotent — no-op if the record is already active.
* `await post.force_delete()` — bypasses the soft-delete override and issues a real `DELETE` to the DB.
* `post.is_trashed` — property, returns `True` if the record is soft-deleted.

**Class methods:**
* `await Post.with_trashed().all()` — retrieves all records including deleted.
* `await Post.only_trashed().all()` — retrieves only soft-deleted records.

### NoriTreeMixin (Advanced Recursive Adjacency CTE)
Converts a table into a self-referential recursive ecosystem. Useful for infinite categories, nested permissions, or corporate hierarchies. Explicitly requires a Foreign Key field named `"parent"`.

```python
from core.mixins.tree import NoriTreeMixin

class Category(NoriTreeMixin):
    name = fields.CharField(max_length=100)
    parent = fields.ForeignKeyField('models.Category', related_name='children_rel', null=True, default=None)
```

Natively injected functions:
* `await node.children()` -> Direct children of the node.
* `await node.parent_node()` -> Parent node (None if root).
* `await node.ancestors()` -> All ancestors via recursive CTE (single query, from node up to root).
* `await node.descendants()` -> All descendants via recursive CTE (single query).
* `await node.siblings()` -> Siblings (same parent, excluding self).
* `await node.is_leaf()` -> True if the node has no children.
* `await node.is_root()` -> True if the node has no parent.
* `await node.move_to(new_parent_id=5)` -> Move node to a new parent (validates against cycles).
* `await Category.tree()` -> Load the entire tree in one query, structured in memory.
* `await Category.tree(root_id=5)` -> Load only the subtree under node 5 (children of that node, structured recursively).
