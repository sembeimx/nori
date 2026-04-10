# Nori

[![Tests](https://github.com/sembeimx/nori/actions/workflows/tests.yml/badge.svg)](https://github.com/sembeimx/nori/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org)
[![Version](https://img.shields.io/github/v/release/sembeimx/nori)](https://github.com/sembeimx/nori/releases)

A batteries-included async Python web framework built on **Starlette** and **Tortoise ORM**.

Class-based controllers, declarative validation (`required|email|max:255` — 17 built-in rules), native authentication (sessions, JWT, OAuth2), CSRF protection, granular ACL permissions, audit logging, persistent job queues (database + Redis), WebSockets, rate limiting, pluggable CLI, testing utilities, and a self-updating core.

---

## Quick Start

```bash
git clone https://github.com/sembeimx/nori.git my-project
cd my-project
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example rootsystem/application/.env
python3 nori.py serve
```

Open `http://localhost:8000`.

### Configuration (.env)

**SQLite** (quickest for development):

```env
DEBUG=true
SECRET_KEY=my-secret-key
DB_ENGINE=sqlite
DB_NAME=db.sqlite3
```

**MySQL / PostgreSQL:** see the [deployment guide](https://nori.sembei.mx/deployment/).

### Docker

```bash
cp .env.example rootsystem/application/.env
# Set DB_ENGINE=mysql and DB_HOST=db in .env
docker compose up -d --build
```

---

## CLI

All commands run from the project root. Built-in commands live in `core/cli.py` (updated with `framework:update`). Custom commands go in `commands/*.py` — they survive updates.

| Command | Description |
|---------|-------------|
| `python3 nori.py serve` | Dev server with hot reload |
| `python3 nori.py make:controller Name` | Scaffold a controller |
| `python3 nori.py make:model Name` | Scaffold a model |
| `python3 nori.py make:seeder Name` | Scaffold a seeder |
| `python3 nori.py migrate:init` | Initialize migration system |
| `python3 nori.py migrate:make <name>` | Create a migration |
| `python3 nori.py migrate:upgrade` | Run pending migrations |
| `python3 nori.py migrate:downgrade` | Roll back last migration |
| `python3 nori.py db:seed` | Run database seeders |
| `python3 nori.py queue:work` | Start the job queue worker |
| `python3 nori.py audit:purge` | Purge old audit log entries |
| `python3 nori.py framework:update` | Update Nori core from GitHub |
| `python3 nori.py framework:version` | Show current version |

---

## Project Structure

```
nori/
├── nori.py                          ← CLI bootstrap (delegates to core/cli.py)
├── requirements.txt
├── tests/
└── rootsystem/
    ├── static/                      ← CSS, JS, images
    ├── templates/                   ← Jinja2 views
    └── application/
        ├── asgi.py                  ← ASGI entry point and middleware stack
        ├── settings.py              ← Configuration via environment variables
        ├── routes.py                ← Named routes with Mount grouping
        ├── commands/                ← Custom CLI commands (survive framework:update)
        ├── models/                  ← Application models
        │   └── framework/           ← Framework-owned models (AuditLog, Job)
        ├── modules/                 ← Controllers
        ├── seeders/                 ← Database seeders
        └── core/                    ← Framework engine (updated via framework:update)
            ├── cli.py               ← CLI commands + plugin loader
            ├── conf.py              ← Config provider
            ├── registry.py          ← Model registry (IoC)
            ├── testing.py           ← Test utilities (client, factories, auth)
            ├── collection.py        ← NoriCollection
            ├── pagination.py        ← Async paginator
            ├── queue.py             ← Job queue (memory/database/redis drivers)
            ├── queue_worker.py      ← Queue worker with retry and dead letters
            ├── auth/                ← Sessions, JWT, CSRF, OAuth2, ACL decorators
            ├── http/                ← @inject DI, validation (17 rules)
            └── mixins/              ← NoriModelMixin, NoriSoftDeletes, NoriTreeMixin
```

---

## Documentation

Full documentation at **[nori.sembei.mx](https://nori.sembei.mx)**.

- [Routing](https://nori.sembei.mx/routing/) — HTTP verbs, path params, reverse routing
- [Controllers](https://nori.sembei.mx/controllers/) — Class-based handlers, `@inject` DI
- [Database](https://nori.sembei.mx/database/) — Tortoise ORM, migrations, soft deletes, tree models
- [Templates](https://nori.sembei.mx/templates/) — Jinja2 views, layouts, static files
- [Authentication](https://nori.sembei.mx/authentication/) — Sessions, JWT, OAuth2, ACL
- [Validation](https://nori.sembei.mx/forms_validation/) — Declarative pipe-separated rules
- [Collections](https://nori.sembei.mx/collections/) — NoriCollection with filtering, sorting, pagination
- [Security](https://nori.sembei.mx/security/) — CSRF, rate limiting, security headers
- [Background Tasks](https://nori.sembei.mx/background_tasks/) — Volatile tasks and persistent job queues (database + Redis)
- [Services](https://nori.sembei.mx/services/) — Email, file storage, search, audit logging
- [WebSockets](https://nori.sembei.mx/websockets/) — Real-time with session/JWT auth
- [Testing](https://nori.sembei.mx/testing/) — Test client, factories, auth helpers, assertions
- [Deployment](https://nori.sembei.mx/deployment/) — Gunicorn, systemd, Nginx, Docker, Redis
- [CLI Reference](https://nori.sembei.mx/cli/) — All commands and plugin system

---

## Testing

```bash
pip install -r requirements-dev.txt
DEBUG=true pytest tests/ -v
```

Tests boot the full ASGI app against an in-memory SQLite database using `httpx.AsyncClient`. No external services required. Nori includes `core.testing` with helpers for testing your own app — see the [testing docs](https://nori.sembei.mx/testing/).

---

## Updating

Projects built with Nori can update the framework core with a single command:

```bash
python3 nori.py framework:update
```

This downloads the latest release from GitHub, backs up the current core, and replaces it. See the [CLI docs](https://nori.sembei.mx/cli/) for options.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

MIT — see [LICENSE](LICENSE).
