# Nori Framework

**Opinionated async web framework for Python** — structured, secure, and lightweight.

---

## What is Nori?

Nori is a full-stack async web framework that makes decisions for you: project structure, authentication, validation, controllers, and CLI generators — all built-in, all async-native.

- **~3,400 lines of core** — small enough to read, big enough to ship
- **Built-in auth + ACL** — sessions, JWT, OAuth2, roles, granular permissions
- **Tortoise ORM** — async database layer with migrations
- **CLI generators** — scaffold controllers, models, seeders
- **Convention over configuration** — a right place for everything

---

## Quick Start

```bash
# Clone and install
git clone https://gitlab.com/sembeimexico/nori.git my-project
cd my-project
pip install -r requirements.txt

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
pytest tests/
```

---

## Key Features

- **Session Auth + JWT** — Login, roles, granular permissions (ACL), brute-force protection
- **OAuth2** — Google (OpenID Connect + PKCE) and GitHub drivers included
- **Declarative Validation** — Pipe-separated syntax: `'required|email|max:255'`
- **Multi-Driver Services** — Storage, Email, Search, Cache with pluggable backends
- **Background Tasks** — Volatile (`background()`) and persistent job queues (`push()`)
- **WebSockets** — Handler base classes with session/JWT auth
- **Security by Default** — CSRF, security headers, magic byte upload verification, protected fields
- **CLI Generators** — Scaffold controllers, models, seeders, and migrations
- **Framework Updates** — `python3 nori.py framework:update` pulls the latest core from GitLab

---

## Documentation

| Section | Description |
|---------|-------------|
| **[Architecture](architecture.md)** | Request lifecycle, middleware stack, dependency injection |
| **[Authentication](authentication.md)** | Sessions, JWT, OAuth2, ACL, brute-force protection |
| **[Controllers](controllers.md)** | Request handling, `@inject()`, security decorators |
| **[Database](database.md)** | Tortoise ORM, migrations, soft deletes, tree structures |
| **[Security](security.md)** | CSRF, headers, rate limiting, upload verification, JWT |
| **[Services](services.md)** | Storage, email, search, audit logging with driver pattern |
| **[Deployment](deployment.md)** | Gunicorn, Apache/Nginx, Docker, sizing guide |
| **[CLI Reference](cli.md)** | All commands: serve, make:\*, migrate:\*, framework:\* |

---

<p align="center">
  Built by <a href="https://sembei.mx">Sembei</a>
</p>
