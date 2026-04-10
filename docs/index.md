# Nori Framework

**Opinionated async web framework for Python** — structured, secure, and lightweight.

---

## What is Nori?

Nori is a full-stack async web framework that makes decisions for you: project structure, authentication, validation, controllers, and CLI generators — all built-in, all async-native.

- **Built-in auth + ACL** — sessions, JWT, OAuth2, roles, granular permissions
- **Tortoise ORM** — async database layer with migrations
- **CLI generators + plugin system** — scaffold controllers, models, seeders; extend with your own commands
- **Convention over configuration** — a right place for everything

---

## Quick Start

```bash
# Clone and install
git clone https://github.com/sembeimx/nori.git my-project
cd my-project
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp .env.example rootsystem/application/.env
# Edit .env: set DB_ENGINE=sqlite, DB_NAME=db.sqlite3

# Start the dev server
python3 nori.py serve
```

Visit `http://localhost:8000` to see the welcome page.

---

## Create Your First Feature

Nori follows a **7-step protocol** for adding features:

```bash
# 1. Create a model
python3 nori.py make:model Article

# 2. Register it in models/__init__.py (the CLI tells you)

# 3. Create and run migrations
python3 nori.py migrate:make create_articles
python3 nori.py migrate:upgrade

# 4. Create a controller
python3 nori.py make:controller Article

# 5. Define routes in routes.py
# 6. Create templates in templates/article/
# 7. Run tests
pip install -r requirements-dev.txt
DEBUG=true pytest tests/
```

---

## Key Features

- **Session Auth + JWT** — Login, roles, granular permissions (ACL), brute-force protection, JWT revocation, session permissions TTL
- **OAuth2** — Google (OpenID Connect + PKCE) and GitHub drivers included
- **Declarative Validation** — 17 built-in rules with pipe syntax: `'required|email|max:255|url|date|confirmed|nullable'`
- **Multi-Driver Services** — Storage, Email, Search, Cache with pluggable backends and memory backend guards
- **Background Tasks** — Volatile (`background()`) and persistent job queues (`push()`) with database and Redis drivers
- **WebSockets** — Handler base classes with session/JWT auth
- **Collections** — Chainable `NoriCollection` with filtering, sorting, grouping, and aggregation
- **Security by Default** — CSRF, security headers, magic byte upload verification, protected fields
- **CLI + Plugin System** — Built-in generators plus custom commands in `commands/` that survive framework updates
- **Testing Utilities** — Test client, model factories, session auth helpers, and assertion helpers
- **Framework Updates** — `python3 nori.py framework:update` pulls the latest core from GitHub

---

## Documentation

| Section | Description |
|---------|-------------|
| **[Architecture](architecture.md)** | Request lifecycle, middleware stack, dependency injection |
| **[Authentication](authentication.md)** | Sessions, JWT, OAuth2, ACL, brute-force protection |
| **[Controllers](controllers.md)** | Request handling, `@inject()`, security decorators |
| **[Routing](routing.md)** | Route definitions, mounts, dot-notation names |
| **[Database](database.md)** | Tortoise ORM, migrations, soft deletes, tree structures |
| **[Templates](templates.md)** | Jinja2 views, layouts, CSRF fields |
| **[Forms & Validation](forms_validation.md)** | Declarative rules, file validation, error handling |
| **[Collections](collections.md)** | Chainable filtering, sorting, grouping, aggregation |
| **[Security](security.md)** | CSRF, headers, rate limiting, upload verification, JWT |
| **[Services](services.md)** | Storage, email, search, audit logging with driver pattern |
| **[Caching](caching.md)** | Cache drivers and usage patterns |
| **[Background Tasks](background_tasks.md)** | Volatile tasks and persistent job queues |
| **[WebSockets](websockets.md)** | Handler base classes with session/JWT auth |
| **[Flash Messages](flash_messages.md)** | Session-based flash notifications |
| **[Logging](logging.md)** | Request ID tracing and structured logging |
| **[Deployment](deployment.md)** | Gunicorn, Apache/Nginx, Docker, sizing guide |
| **[Testing](testing.md)** | Test client, model factories, auth helpers, assertions |
| **[CLI Reference](cli.md)** | All commands, plugin system for custom commands |
| **[Philosophy](philosophy.md)** | Design principles and framework goals |
| **[Roadmap](roadmap.md)** | Planned features and development direction |

---

<p align="center">
  Built by <a href="https://sembei.mx">Sembei</a>
</p>
