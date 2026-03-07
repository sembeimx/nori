# Roadmap — What's needed for a large-scale app

Current state of Nori and the pieces needed to support production-grade applications at scale.

---

## What already exists

| Area | Implemented |
|------|-------------|
| **HTTP** | Security headers, CORS, sessions, CSRF, rate limiting (with pluggable backends), flash messages, Request ID tracing |
| **Auth** | Login/logout/register, password hashing PBKDF2, role decorators (`login_required`, `require_role`, `require_any_role`), JWT with `@token_required`, granular ACL (`@require_permission`, `load_permissions`) |
| **Validation** | Declarative rules: `required`, `min`, `max`, `email`, `numeric`, `matches`, `in`, `file`, `file_max`, `file_types`. Custom messages |
| **Database** | Tortoise ORM (MySQL, PostgreSQL, SQLite), soft deletes, tree mixin with recursive CTEs, `to_dict()`, Aerich migrations (`migrate:init`, `migrate:make`, `migrate:upgrade`, `migrate:downgrade`) |
| **File Uploads** | `save_upload()` with extension, MIME type, max size validation, UUID filenames |
| **Email** | `send_mail()` with aiosmtplib, Jinja2 template support, MIME multipart |
| **JWT / API Tokens** | Manual HMAC-SHA256 (`create_token`, `verify_token`), `@token_required` decorator for APIs |
| **Rate Limiting** | Pluggable backends: `MemoryBackend` (default) and `RedisBackend` (sorted sets). Config via `THROTTLE_BACKEND` |
| **Caching** | Pluggable backends: `MemoryCacheBackend` (default) and `RedisCacheBackend`. `cache_get`, `cache_set`, `cache_delete`, `cache_flush`, `@cache_response` decorator |
| **Background Tasks** | `background()`, `background_tasks()`, `run_in_background()` wrapping Starlette's `BackgroundTask` with error logging |
| **WebSockets** | `WebSocketHandler` and `JsonWebSocketHandler` base classes, `/ws/echo` demo route |
| **Utilities** | NoriCollection (17 methods), async pagination, flash messages |
| **Templates** | Jinja2 with globals (`csrf_field`, `get_flashed_messages`), email base template |
| **Config** | `.env` with `python-dotenv`, centralized settings, startup validation |
| **Logging** | Production-grade `nori.*` logger with JSON/text formatters, rotating file handler, env-based config (`LOG_LEVEL`, `LOG_FORMAT`, `LOG_FILE`) |
| **Deployment** | Multi-stage Dockerfile, docker-compose.yml (app + MySQL), Gunicorn with UvicornWorker |
| **Error Handling** | Custom handlers for 404 (JSON + HTML) and 500 |
| **Health Check** | `GET /health` endpoint with DB connectivity check (200/503) |
| **DB Seeding** | Convention-based seeder system with `db:seed` and `make:seeder` CLI commands |
| **Test Factories** | `make_article()`, `make_post()`, `make_category()` factory functions with auto-incrementing defaults |
| **Audit Logging** | `AuditLog` model, `audit()` background task, `get_client_ip()`, structured logging with request ID tracing |
| **Tests** | pytest + pytest-asyncio, 264 tests (unit + E2E with httpx), `asyncio_mode = auto` |

---

## What's next

### Priority 4 — Advanced features

| Feature | Description | Status |
|---------|-------------|--------|
| **Admin panel** | Auto-generated CRUD interface from models | Planned |
| **OAuth / Social login** | Login with Google, GitHub, etc. | Planned |
| **Granular permissions (ACL)** | `require_permission('articles.edit')` decorator, `Permission` + `Role` models with M2M, `load_permissions()` for session caching | **Done** |
| **i18n** | Internationalization of messages and templates | Planned |
| **OpenAPI / Swagger** | Automatic API endpoint documentation | Planned |
| **Audit logging** | `AuditLog` model + `audit()` background task utility with structured logging, IP tracking, and request ID tracing | **Done** |
| **2FA** | Two-factor authentication (TOTP) | Planned |

Each item is independent and can be implemented without affecting the others. The current architecture supports all of these additions without refactoring.
