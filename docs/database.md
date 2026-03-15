# Database (Tortoise ORM)

In Nori, asynchronous database mapping (ORM) is handled by **Tortoise ORM**. It is highly inspired by Django's ORM but is 100% non-blocking (`async/await`).

## Connection and Configuration

The engines (MySQL, PostgreSQL, SQLite) are defined in the `.env` file. The framework parses the requested engine in the central configuration file `rootsystem/application/settings.py`.

Make sure to document and register your Models inside `settings.py` (in the `TORTOISE_ORM['apps']['models']['models']` dictionary) so that Tortoise locates them immediately and allows inter-relationships.

## Defining a Model

Models are located in the `rootsystem/application/models/` directory. They must inherit from `Model` and optionally from any Nori Mixins you wish to use.

```python
from tortoise.models import Model
from tortoise import fields
from core.mixins.model import NoriModelMixin

class User(NoriModelMixin, Model):
    id = fields.IntField(primary_key=True)
    slug = fields.CharField(max_length=50, unique=True)
    name = fields.CharField(max_length=100)
    level = fields.IntField(default=0)
    status = fields.BooleanField(default=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = 'user'  # Recommended: explicitly specify the SQL table name
```

### NoriModelMixin (`to_dict`)
Inheriting this mixin alongside the Tortoise Model adds vital functionality for dispatching pure JSON responses. It exclusively injects the `.to_dict(self, exclude=[])` method, stripping away ORM metadata and internal instances, automatically resolving everything into primitive variables.

```python
user = await User.get(id=1)
# Quick JSON dump omitting sensitive fields:
data = user.to_dict(exclude=['id', 'level'])
```

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

Tracks who did what and when. Entries are created as background tasks via `audit()` from `core.audit`.

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

### NoriSoftDeletes (Logical Deletion)
Protects transactional entropy by preventing hard `DROP` or `DELETE` SQL operations. Requires the model to have a `deleted_at (TIMESTAMP NULL)` column in the database.

```python
from core.mixins.soft_deletes import NoriSoftDeletes

class Post(NoriSoftDeletes):  # <--- Replace "Model" with "NoriSoftDeletes"
    title = fields.CharField()
```

Available functions:
* `await post.delete()` -> Silently sets the status and updates *deleted_at* with `NOW()`. When running `filter()` via the `objects` manager, soft-deleted records are automatically excluded.
* `await post.restore()` -> Sets *deleted_at* back to Null, returning it to the active filter.
* `await post.force_delete()` -> Bypasses the override, issuing a real DELETE to the DB.
* `await Post.with_trashed().all()` -> Retrieves all records including deleted.
* `await Post.only_trashed().all()` -> Excludes active records, showing only soft-deleted ones.

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
