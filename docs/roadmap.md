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
| **Background Tasks** | `background()` (volatile) and `push()` (persistent) with multi-driver support (Memory, Database). Error logging and retries included |
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
| **Job Queue (Persistent)** | `push()` dispatcher with Database/Memory drivers. Features: **Atomic locking**, **Exponential backoff**, **Dead letters** (`failed_at`), **Graceful shutdown**, and `queue:work` CLI |
| **Granular permissions (ACL)** | `require_permission('articles.edit')` decorator, `Permission` + `Role` models with M2M, `load_permissions()` for session caching |
| **Audit logging** | `AuditLog` model + `audit()` background task with structured logging, IP tracking, and request ID tracing |
| **Multi-driver Email** | `send_mail()` refactored with driver registry. Built-in: `smtp` (production), `log` (development). Custom drivers via `register_mail_driver()` |
| **Multi-driver Storage** | `save_upload()` refactored with driver registry. Built-in: `local` (disk). Custom drivers via `register_storage_driver()`. S3 example in `services/` |
| **Search dispatcher** | `core/search.py` with `search()`, `index_document()`, `remove_document()`. No built-in driver — external engines only. Meilisearch example in `services/` |
| **Security hardening** | `protected_fields` on models to prevent data leaks in `to_dict()`, magic byte verification on uploads (pure Python, no libmagic), JWT secret minimum length (32 chars) enforced at startup |

---

## Production hardening — Before going live

These are not new features — they are gaps in existing subsystems that must be addressed before serving real traffic. Ordered by severity.

### P0 — Must fix

| Gap | Problem | Fix |
|-----|---------|-----|
| **Memory cache unbounded growth** | `MemoryCacheBackend` has no max key limit. Under sustained load, the cache grows until the process runs out of memory (OOM kill). | Add a `max_keys` parameter with LRU eviction. Default to a sensible limit (e.g. 10,000 keys). Document that Redis is strongly recommended for production. |
| **Memory backends unsuitable for production** | Both `MemoryCacheBackend` and `MemoryThrottleBackend` lose all state on restart or deploy. Rate limit counters reset, cached data vanishes. With multiple workers (Gunicorn), each process has its own isolated store — rate limits become ineffective. | Add a startup warning when `DEBUG=False` and memory backends are active. Document Redis as the production requirement for cache and rate limiting. |

### P1 — Fix before real users have accounts

| Gap | Problem | Fix |
|-----|---------|-----|
| ~~**No brute-force protection on login**~~ | ~~An attacker can attempt passwords against a known email indefinitely.~~ | **Done** — `check_login_allowed()`, `record_failed_login()`, `clear_failed_logins()` in `core/auth/login_guard.py`. Per-account lockout with escalating backoff (1m → 5m → 15m → 30m → 1h). Uses cache backend. |
| **Session permissions never invalidate** | `load_permissions()` caches the user's roles and permissions in the session. If an admin revokes a role, the user keeps their old permissions until their session expires or they log out. | Add a TTL or version check: store a `permissions_loaded_at` timestamp in the session and re-fetch after a configurable interval (e.g. 5 minutes). |
| **JWT has no revocation mechanism** | Once issued, a JWT is valid until it expires. A compromised token cannot be invalidated. | Implement a lightweight token blacklist (DB or cache-backed) checked on `@token_required`. Add an optional `jti` (JWT ID) claim for selective revocation. |

---

## What's next — Priority order

### 1. Social Auth (OAuth2)

**Why it's #1**: Almost every modern app needs "Login with Google/GitHub". It's HTTP-based (fits Nori's async nature) and has a clear, bounded scope.

**Design**:
- Lives in `services/`, not in core — each provider has different flows (Google uses OpenID Connect, GitHub doesn't, Apple requires server-side JWT)
- Example drivers: `services/oauth_google.py`, `services/oauth_github.py`
- Each driver exposes: `get_auth_url(redirect_uri)`, `handle_callback(code)`, `get_user_profile(token)`
- Uses `httpx` (already a dependency) for token exchange
- The programmer handles user creation/association in their controller — Nori doesn't touch models

**Filosofía**: No abstraction layer in core. Each provider is a standalone service file. The programmer calls 3 functions explicitly.

### 2. OpenAPI / Swagger

**Why it's #2**: The most valuable feature Nori lacks for public APIs. Auto-generated docs from route definitions.

**Concerns**: Pipe-separated validation (`'required|email|max:255'`) doesn't map cleanly to OpenAPI schemas. May require adding optional type metadata to routes.

...
