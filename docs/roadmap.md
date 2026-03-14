# Roadmap — What's needed for a large-scale app

Current state of Nori and the pieces needed to support production-grade applications at scale.

---

## What already exists

| Area | Implemented |
|------|-------------|
| **HTTP** | Security headers, CORS, sessions, CSRF, rate limiting (pluggable backends), flash messages, Request ID tracing |
| **Auth** | Login/logout/register, password hashing PBKDF2, role decorators (`login_required`, `require_role`, `require_any_role`), JWT with `@token_required`, granular ACL (`@require_permission`, `load_permissions`) |
| **Validation** | Declarative rules: `required`, `min`, `max`, `email`, `numeric`, `matches`, `in`, `file`, `file_max`, `file_types`. Custom messages |
| **Database** | Tortoise ORM (MySQL, PostgreSQL, SQLite), soft deletes, tree mixin with recursive CTEs, `to_dict()` with `protected_fields`, Aerich migrations |
| **Storage** | Multi-driver `save_upload()` with extension, MIME, magic byte content verification, size validation, UUID filenames. Built-in: `local`. Extensible via `register_storage_driver()`. Example: `services/storage_s3.py` |
| **Email** | Multi-driver `send_mail()` with Jinja2 templates, MIME multipart. Built-in: `smtp`, `log`. Extensible via `register_mail_driver()`. Example: `services/mail_resend.py` |
| **Search** | Multi-driver dispatcher (`search()`, `index_document()`, `remove_document()`). No built-in driver (opt-in). Extensible via `register_search_driver()`. Example: `services/search_meilisearch.py` |
| **JWT / API Tokens** | Manual HMAC-SHA256 (`create_token`, `verify_token`), `@token_required` decorator for APIs, minimum secret length enforcement (32 chars) |
| **Rate Limiting** | Pluggable backends: `MemoryBackend` (default) and `RedisBackend` (sorted sets). Config via `THROTTLE_BACKEND` |
| **Caching** | Pluggable backends: `MemoryCacheBackend` (default) and `RedisCacheBackend`. `cache_get`, `cache_set`, `cache_delete`, `cache_flush`, `@cache_response` decorator |
| **Background Tasks** | `background()`, `background_tasks()`, `run_in_background()` wrapping Starlette's `BackgroundTask` with error logging |
| **WebSockets** | `WebSocketHandler` and `JsonWebSocketHandler` base classes, `/ws/echo` demo route |
| **Utilities** | NoriCollection (17 methods), async pagination, flash messages |
| **Templates** | Jinja2 with globals (`csrf_field`, `get_flashed_messages`), email base template |
| **Config** | `.env` with `python-dotenv`, centralized settings, startup validation |
| **Logging** | Production-grade `nori.*` logger with JSON/text formatters, rotating file handler, env-based config (`LOG_LEVEL`, `LOG_FORMAT`, `LOG_FILE`) |
| **Audit Logging** | `AuditLog` model, `audit()` background task, `get_client_ip()`, structured logging with request ID tracing |
| **Deployment** | Multi-stage Dockerfile, docker-compose.yml (app + MySQL), Gunicorn with UvicornWorker |
| **Error Handling** | Custom handlers for 404 (JSON + HTML) and 500 |
| **Health Check** | `GET /health` endpoint with DB connectivity check (200/503) |
| **DB Seeding** | Convention-based seeder system with `db:seed` and `make:seeder` CLI commands |
| **Test Factories** | `make_article()`, `make_post()`, `make_category()` factory functions with auto-incrementing defaults |
| **Tests** | pytest + pytest-asyncio, 318 tests (unit + E2E with httpx), `asyncio_mode = auto` |

### Recently completed

| Feature | Description |
|---------|-------------|
| **Granular permissions (ACL)** | `require_permission('articles.edit')` decorator, `Permission` + `Role` models with M2M, `load_permissions()` for session caching |
| **Audit logging** | `AuditLog` model + `audit()` background task with structured logging, IP tracking, and request ID tracing |
| **Multi-driver Email** | `send_mail()` refactored with driver registry. Built-in: `smtp` (production), `log` (development). Custom drivers via `register_mail_driver()` |
| **Multi-driver Storage** | `save_upload()` refactored with driver registry. Built-in: `local` (disk). Custom drivers via `register_storage_driver()`. S3 example in `services/` |
| **Search dispatcher** | `core/search.py` with `search()`, `index_document()`, `remove_document()`. No built-in driver — external engines only. Meilisearch example in `services/` |
| **Security hardening** | `protected_fields` on models to prevent data leaks in `to_dict()`, magic byte verification on uploads (pure Python, no libmagic), JWT secret minimum length (32 chars) enforced at startup |

---

## What's next — Priority order

### 1. Job Queue (persistent, with retries)

**Why it's #1**: `background()` runs in-process — if the server restarts, tasks are lost. Every production app eventually needs reliable async work: bulk emails, PDF generation, image processing, search re-indexing. A queue system unblocks all of these.

**Design**:
- `core/queue.py` — dispatcher with the same driver pattern as mail/storage/search
- Built-in driver: `database` (uses the existing DB, zero new dependencies)
- External driver: `services/queue_redis.py` (for high-throughput)
- CLI: `python3 nori.py queue:work` to run a worker process
- Features: serialized tasks, automatic retries with backoff, dead letter tracking, `@job` decorator
- Config: `QUEUE_DRIVER=database` (default) or `QUEUE_DRIVER=redis`

**Filosofía**: The `database` driver keeps it native (no Redis required to start). Redis is opt-in for scale.

### 2. Social Auth (OAuth2)

**Why it's #2**: Almost every modern app needs "Login with Google/GitHub". It's HTTP-based (fits Nori's async nature) and has a clear, bounded scope.

**Design**:
- Lives in `services/`, not in core — each provider has different flows (Google uses OpenID Connect, GitHub doesn't, Apple requires server-side JWT)
- Example drivers: `services/oauth_google.py`, `services/oauth_github.py`
- Each driver exposes: `get_auth_url(redirect_uri)`, `handle_callback(code)`, `get_user_profile(token)`
- Uses `httpx` (already a dependency) for token exchange
- The programmer handles user creation/association in their controller — Nori doesn't touch models

**Filosofía**: No abstraction layer in core. Each provider is a standalone service file. The programmer calls 3 functions explicitly.

### 3. OpenAPI / Swagger

**Why it's #3**: The most valuable feature Nori lacks for public APIs. Auto-generated docs from route definitions.

**Concerns**: Pipe-separated validation (`'required|email|max:255'`) doesn't map cleanly to OpenAPI schemas. May require adding optional type metadata to routes.

### 4. Admin panel

Auto-generated CRUD interface from models. Useful but not blocking — most teams build custom admin UIs.

### 5. i18n

Internationalization of messages and templates. Important for global apps, but can be added later without breaking changes.

### 6. 2FA (TOTP)

Two-factor authentication. Security enhancement, bounded scope, no external dependencies (HMAC-based).

---

## Under evaluation

The following features have been identified through architectural analysis and framework comparisons (Litestar, Laravel, FastAPI). They are documented here to keep them visible, but **none are committed to**.

### Infrastructure

| Feature | What it would solve | Status |
|---------|---------------------|--------|
| **Events / Listeners** | Decouple side effects from controllers (e.g. "on user created → send email + write audit log") | **Deferred** — Nori's simplicity comes from explicit code in controllers. Implicit event chains make debugging harder. Not needed yet. |
| **Scheduler** | Run periodic tasks from code instead of system crontab | **Deferred** — Requires a long-running process. Adds operational complexity for something cron already solves. |
| **Notifications system** | Unified multi-channel notifications (mail, SMS, webhook) via a single API | **Deferred** — `send_mail()` + explicit driver calls cover the primary cases. A full notification system with channel classes would break Nori's function-based ergonomics. Revisit when there's real demand. |
| **Media Library** | Image thumbnails, optimization, WebP conversion on upload | **Rejected** — Requires Pillow (10MB+ C dependency), violates "Keep it Native". Image processing should happen in a queue worker or external service (imgproxy, Cloudflare Images), not in the web process. |

### API & Data

| Feature | What it would solve | Status |
|---------|---------------------|--------|
| **API Resources** | Consistent JSON transformation layer for models | **Deferred** — `to_dict(exclude=[...])` convention is enough for now |
| **Database Transactions** | Ergonomic wrapper for `async with in_transaction()` | **Deferred** — Small feature, needs careful design |
| **API versioning** | Convention for `/api/v1/`, `/api/v2/` | **Not needed** — Solved with `Mount('/api/v1', routes=[...])`, no framework code required |

### Developer Experience

| Feature | What it would solve | Status |
|---------|---------------------|--------|
| **Testing helpers** | `acting_as(user)`, `assert_database_has()` shortcuts | **Deferred** — pytest + httpx works fine |
| **Log context propagation** | Auto-attach `request_id` to all log messages via `ContextVar` | **Deferred** — Small improvement, current manual approach works |

### Distribution

| Feature | What it would solve | Status |
|---------|---------------------|--------|
| **`nori init` command** | Generate a clean project scaffold | **Planned** — Useful intermediate step before pip packaging |
| **Nori as pip package** | `pip install nori-framework` — separates core from user code | **Future (v2.0)** — Biggest architectural change. Requires restructuring the project. |

---

## Evaluation criteria

Before implementing any feature, ask:

1. **Does it stay native?** Nori avoids heavy external dependencies. If a feature requires Redis, Celery, or a new runtime, it needs strong justification.
2. **Does it break simplicity?** A developer should be able to read any Nori controller and understand exactly what happens. Implicit magic (events, middleware chains, auto-serialization) can erode that.
3. **Is it needed now?** If no real project is blocked by the absence of this feature, it can wait.
4. **Can it be a convention instead of code?** Some "features" (API versioning, transaction helpers) might be better solved with documentation and patterns rather than new framework code.
