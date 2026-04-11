# Roadmap

Current state of Nori and what's coming next.

---

## What already exists

| Area | Implemented |
|------|-------------|
| **HTTP** | Security headers, CORS, sessions, CSRF, rate limiting (pluggable backends), flash messages, Request ID tracing |
| **Auth** | Login/logout, PBKDF2 password hashing, role decorators, JWT with `@token_required`, granular ACL (`@require_permission`), brute-force protection, OAuth2 (Google + GitHub) |
| **Validation** | Declarative pipe-separated rules: `required`, `min`, `max`, `email`, `numeric`, `matches`, `in`, `url`, `date`, `confirmed`, `nullable`, `array`, `min_value`, `max_value`, `regex`, `file`, `file_max`, `file_types` |
| **Database** | Tortoise ORM (MySQL, PostgreSQL, SQLite), soft deletes, tree mixin (recursive CTEs), `to_dict()` with `protected_fields`, Aerich migrations with separate framework/app namespaces |
| **Storage** | Multi-driver `save_upload()` with extension, MIME, and magic byte verification. Built-in: `local`. Example: `services/storage_s3.py` |
| **Email** | Multi-driver `send_mail()` with Jinja2 templates. Built-in: `smtp`, `log`. Example: `services/mail_resend.py` |
| **Search** | Multi-driver dispatcher. No built-in driver (opt-in). Example: `services/search_meilisearch.py` |
| **Caching** | LRU memory backend (max 10,000 keys) + Redis backend. `@cache_response` decorator |
| **Background Tasks** | `background()` (volatile) + `push()` (persistent job queue with memory, database, and Redis drivers; atomic locking, exponential backoff, dead letters) |
| **WebSockets** | `WebSocketHandler` and `JsonWebSocketHandler` base classes |
| **Architecture** | Decoupled core via `core.conf` (config provider) and `core.registry` (model registry). Framework-agnostic to application code |
| **CLI** | `serve`, `make:controller`, `make:model`, `make:seeder`, `migrate:*`, `db:seed`, `queue:work`, `framework:update`, `framework:version` |
| **Deployment** | Dockerfile, docker-compose, Gunicorn config, Apache/Nginx examples, MkDocs documentation site |
| **Tests** | 519 tests (pytest + pytest-asyncio), unit + E2E with httpx |

---

## Production hardening — All resolved

All production-critical gaps have been addressed:

| Item | Solution |
|------|----------|
| **Memory backend warnings** | `asgi.py` logs warnings at startup when `DEBUG=False` and `CACHE_BACKEND` or `THROTTLE_BACKEND` is `memory`. |
| **LRU cache eviction** | `MemoryCacheBackend` uses LRU with `max_keys` (default 10,000). Configurable via `CACHE_MAX_KEYS`. |
| **Brute-force protection** | Per-account lockout with escalating backoff (1m → 5m → 15m → 30m → 1h) via `core/auth/login_guard.py`. |
| **Session permissions TTL** | `require_permission` auto-refreshes from the database when the cache expires (default: 5 minutes, configurable via `PERMISSIONS_TTL`). |
| **JWT revocation** | `revoke_token()` adds the token's `jti` to a cache-backed blacklist. `verify_token()` checks the blacklist automatically. Blacklist entries auto-expire with the token. |

---

## What's next

### ~~1. Redis Queue Driver~~ — Done (v1.3.0)

Implemented. `QUEUE_DRIVER=redis` with BRPOP for near-instant pickup, delayed jobs via sorted sets, and dead letter list. See [Background Tasks](background_tasks.md).

### ~~2. CLI Plugin System~~ — Done (v1.3.0)

Implemented. User commands live in `commands/*.py` with `register(subparsers)` + `handle(args)`. Survive `framework:update`. See [CLI](cli.md#extending-the-cli).

### ~~3. Validation: Additional Rules~~ — Done (v1.3.0)

Added 8 rules: `url`, `date`, `confirmed`, `nullable`, `array`, `min_value`, `max_value`, `regex`. See [Forms & Validation](forms_validation.md). The `unique` rule was added in v1.4.0.

### ~~4. Testing Utilities for App Developers~~ — Done (v1.3.0)

Implemented. `core.testing` provides `create_test_client()`, `setup_test_db()` / `teardown_test_db()`, `authenticate()` / `authenticate_api()`, `ModelFactory` base class, and assertion helpers. See [Testing](testing.md).

### ~~5. `file_max` Negative Value Bug~~ — Done (v1.3.0)

Fixed. `ValueError` from `_parse_size()` is now caught in `_check_rule` and returned as a validation error.

### ~~6. `unique` Validation Rule~~ — Done (v1.4.0)

Implemented. `unique:table,column` checks value uniqueness via async database query. Requires `validate_async()`. Supports `unique:table,column,except_id` for update forms. See [Forms & Validation](forms_validation.md#async-validation-validate_async).

### ~~7. `routes:list` CLI Command~~ — Done (v1.4.0)

Implemented. `python3 nori.py routes:list` prints a table of all registered routes with path, methods, and name. Supports recursive Mount groups and WebSocket routes. See [CLI Reference](cli.md#route-inspection).

### 8. OpenAPI / Swagger

Auto-generated API docs from route definitions. Pipe-separated validation (`'required|email|max:255'`) doesn't map cleanly to OpenAPI schemas — may require optional type metadata on routes.

### 9. Internationalization (i18n)

Translation support for templates and validation messages. The `messages=` parameter in `validate()` is a first step — a full i18n system would load messages from locale files and resolve them automatically. Bilingual documentation site (EN/ES).

### 10. Admin Panel

Leverage `core.registry` to auto-discover registered models. Visual interface for AuditLog inspection, Job queue status, and basic CRUD.
