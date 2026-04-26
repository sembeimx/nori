# Nori Framework

**The async Python framework where server-rendered pages and JSON APIs are first-class peers.**

---

## What is Nori?

Nori is an async web framework built on Starlette and Tortoise ORM, designed for apps that live in both shapes at once — server-rendered pages and JSON APIs as first-class peers, not one bolted onto the other.

This is the shape Nori was built for:

- A SaaS dashboard with an HTMX UI and a JSON endpoint for the mobile client
- An admin panel and a public API for third-party integrations
- A marketing site that also handles webhooks and background jobs

Everything you need to build that app lives in the core. Auth, validation, ORM, queues, WebSockets, CSRF, rate limiting, testing — one of each, integrated. No stitching.

---

## Quick Start

```bash
# Install
curl -fsSL https://nori.sembei.mx/install.py | python3 - my-project
cd my-project
source .venv/bin/activate

# Edit rootsystem/application/.env if you need MySQL/Postgres (defaults to SQLite)

# Initialize the database and start the dev server
python3 nori.py migrate:init
python3 nori.py serve
```

Visit `http://localhost:8000` to see the welcome page.

---

## Create Your First Feature

Nori follows a **7-step protocol** for adding features:

```bash
# 0. First-time setup (once per project): generate framework + user tables for your engine
python3 nori.py migrate:init

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
- **Declarative Validation** — 19 built-in rules with pipe syntax: `'required|email|max:255|url|date|confirmed|nullable'`
- **Form Re-population** — `flash_old()` + `{{ old('field') }}` Jinja helper preserves user input across validation errors, with sensitive fields auto-excluded
- **Multi-Driver Services** — Storage, Email, Search, Cache with pluggable backends and memory backend guards
- **Background Tasks** — Volatile (`background()`) and persistent job queues (`push()`) with database and Redis drivers
- **WebSockets** — Handler base classes with session/JWT auth
- **Collections** — Chainable `NoriCollection` with filtering, sorting, grouping, and aggregation
- **Security by Default** — CSRF, security headers, magic byte upload verification, protected fields
- **Observability Hook** — `bootstrap.py` runs before Starlette/Tortoise so Sentry, OTel, or Datadog SDKs initialize at the right time
- **CLI + Plugin System** — Built-in generators, async `shell` REPL with models pre-loaded, plus custom commands in `commands/` that survive framework updates
- **Testing Utilities** — Test client, model factories, session auth helpers, and assertion helpers
- **Framework Updates** — `python3 nori.py framework:update` pulls the latest core from GitHub. Split `requirements.nori.txt` keeps framework deps in sync without touching your `requirements.txt`.

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
