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

Focus items that extend the framework's core thesis — server-rendered pages and JSON APIs as first-class peers — plus developer experience wins. For completed work, see the [changelog](https://github.com/sembeimx/nori/blob/main/CHANGELOG.md).

### 1. OpenAPI / Swagger

Auto-generated API documentation from route definitions and declarative validation rules (`'required|email|max:255'`). The validation metadata already describes request shapes — exposing it as an OpenAPI 3 document is a generation step, not a refoundation. This is the keystone for the API-peer side of the framework: every JSON endpoint becomes introspectable, documented, and consumable by codegen tools out of the box.

### 2. Content Negotiation Helpers

First-class support for routes that serve both HTML and JSON from a single controller. Response helpers that return JSON when `Accept: application/json` is present and render the configured template otherwise, plus HTMX-aware utilities (`HX-Redirect`, `HX-Trigger`, partial rendering). This moves the dual-shape thesis from the framework level down to the controller layer where it matters day-to-day.

### 3. Internationalization (i18n)

Translation support for templates and validation messages. The `messages=` parameter in `validate()` is a first step — a full i18n system would load messages from locale files and resolve them automatically. Bilingual documentation site (EN/ES) as a parallel effort.

### 4. Admin Panel

Leverage `core.registry` to auto-discover registered models. Visual interface for AuditLog inspection, Job queue status, and basic CRUD.
