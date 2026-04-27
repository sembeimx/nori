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
| **Observability** | Pre-Starlette `bootstrap.py` hook for Sentry / OpenTelemetry / Datadog SDKs that need to patch libraries at import time. Idempotent `framework:update` patch system wires it into existing sites automatically. |
| **Dependency Management** | Split `requirements.nori.txt` (framework-owned, refreshed on update) + `requirements.txt` (user-owned, `-r`s the framework file). Engine-aware Aerich migrations generated locally per site to avoid SQLite/MySQL/Postgres drift. |
| **CLI** | `serve`, `shell` (async REPL with models pre-loaded), `make:controller`, `make:model`, `make:seeder`, `migrate:*`, `db:seed`, `queue:work`, `framework:update`, `framework:version`, `routes:list`, `audit:purge`, `check:deps` |
| **Forms** | `flash_old()` + `{{ old('field') }}` Jinja helper for re-populating forms across validation errors. Sensitive fields (passwords) auto-excluded. |
| **Deployment** | Dockerfile, docker-compose, Gunicorn config (with `forwarded_allow_ips` defaults for proxied setups), Apache/Nginx/Caddy examples, MkDocs documentation site |
| **Tests** | 720+ tests (pytest + pytest-asyncio + Hypothesis property-based tests on `core/http/validation`), unit + E2E with httpx, CLI command coverage |
| **Code Quality Gates** | Lint (ruff E/W/F/I/UP/B/S/C90), format (ruff), type checking (mypy gradual + per-module strict on `auth.security` / `auth.login_guard` / `auth.csrf` / `auth.jwt` / `auth.oauth` / `http.validation`), test coverage ≥82%, dependency vulnerability scanning (pip-audit), docstring coverage ≥70% (interrogate), secrets scanning (gitleaks), supply-chain SBOM (CycloneDX). All wired to CI on push and PR to main. |

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
| **Fail-fast on misconfigured Redis** (v1.11.0) | `CACHE_BACKEND=redis` and `THROTTLE_BACKEND=redis` now require Redis to be reachable at startup — no more silent fallback to memory. Misconfigured deployments fail boot instead of serving inconsistent state across workers. |
| **Auto-propagated Request-ID** (v1.11.0) | Request-ID stored in a `ContextVar`; every log record under a request automatically carries `record.request_id`, including from `asyncio.create_task` background work. Correlates logs ↔ traces without threading through call signatures. |
| **Deep `/health` + `check:deps` CLI** (v1.12.0) | `/health` now probes DB + cache + throttle, returns 503 if any dependency is down (orchestrator-friendly). `check:deps` CLI runs the same probes pre-deploy / in CI. |

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

### 5. Migration SQL Dry-Run (`migrate:sql`)

A `python3 nori.py migrate:sql` command that prints the **raw SQL** a pending migration will execute against the configured database, without touching it. Aerich generates a Python migration file that's already reviewable, but the actual SQL it produces against your live schema (especially around column renames, where Aerich sometimes infers a destructive `DROP + ADD` instead of `ALTER`) is invisible until `migrate:upgrade` runs.

The implementation needs to either parse Aerich's migration file and replay each operation through Tortoise's schema generator capturing the SQL instead of executing it, or wrap the connection with an interceptor that logs the queries. Aerich 0.9.x does not expose a native `--dry-run` flag, so this is a non-trivial integration — estimated 1 week of work to ship rigorously (a half-baked version that shows SQL that doesn't exactly match what Aerich runs would be worse than nothing).

Pairs naturally with mandatory PR-template review of migration SQL for any change that touches the schema.
