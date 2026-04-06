# Architecture

How Nori processes a request from the network socket to the response, including the middleware stack, dependency injection, and error handling.

Understanding how a request flows through Nori helps you debug faster, write better middleware, and know exactly where to put your logic. There's no magic — just a clear pipeline.

---

## Why This Stack

Nori is built on three foundations, each chosen for a specific reason:

- **Starlette** — A lightweight ASGI framework that gives us routing, middleware, WebSockets, and test clients without imposing opinions on the rest. It's fast, well-maintained, and stays out of the way. We add the opinions on top.
- **Tortoise ORM** — The only Python ORM that is async-native. It doesn't wrap synchronous calls in `run_in_executor` — it speaks async all the way to the database driver. In an async framework, the ORM shouldn't be the piece that blocks the event loop.
- **Jinja2** — The most widely known Python template engine. No proprietary syntax, no learning curve. If you've used it anywhere else, you already know how it works in Nori.

Everything else — authentication, validation, CSRF, JWT, collections, job queues — is built in pure Python with no external dependencies. The core has three runtime dependencies. The rest is ours to maintain, audit, and understand.

---

## Request Lifecycle

Every HTTP request flows through this pipeline:

```
Client → Uvicorn (ASGI) → Middleware Stack → Router → Controller Method → Response
```

### Middleware Stack

Middleware is registered in `asgi.py`. Starlette wraps middleware in order, so the **first registered middleware runs first** during the request phase. Here is the execution order as the request enters:

```
Request ──→ Request ID
              ↓
        Security Headers
              ↓
          CORS (if enabled)
              ↓
           Session
              ↓
            CSRF
              ↓
          Application (Router → Controller)
              ↓
            CSRF
              ↓
           Session
              ↓
          CORS (if enabled)
              ↓
        Security Headers
              ↓
         Request ID
              ↓
Response ←──┘
```

### What Each Middleware Does

| Middleware | Module | Purpose |
|-----------|--------|---------|
| **RequestIdMiddleware** | `core.http.request_id` | Generates a UUID per request (or propagates incoming `X-Request-ID`). Stored in `request.state.request_id`. Added to every response as `X-Request-ID` header. Enables end-to-end tracing across logs and services. |
| **SecurityHeadersMiddleware** | `core.http.security_headers` | Injects security headers on every response: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `X-XSS-Protection: 1; mode=block`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy: camera=(), microphone=(), geolocation=()`, `Strict-Transport-Security` (HSTS, 1 year). Optional CSP if configured. |
| **CORSMiddleware** | `starlette.middleware.cors` | Only added if `CORS_ORIGINS` is set in `.env`. Handles `OPTIONS` preflight and adds `Access-Control-*` headers. |
| **SessionMiddleware** | `starlette.middleware.sessions` | Creates and validates signed session cookies using `SECRET_KEY`. Populates `request.session` as a dict-like object. Required by CSRF, auth decorators, and flash messages. |
| **CsrfMiddleware** | `core.auth.csrf` | Validates CSRF tokens on state-changing methods (POST, PUT, DELETE, PATCH). Skips safe methods (GET, HEAD, OPTIONS) and JSON requests (`application/json`). Checks `X-CSRF-Token` header first, then `_csrf_token` form field. Auto-generates token if missing. Returns 403 on mismatch, 413 on oversized body (DoS protection, 10 MB limit). |

### Why This Order Matters

Middleware order matters. Request ID wraps everything because every log line needs a trace. CSRF runs before your code because forged requests should never reach a controller. Session loads early because auth decorators depend on it.

- **Request ID first**: ensures every log message — including middleware errors — has a trace ID.
- **Security headers early**: guarantees all responses get security headers, even on middleware failures.
- **CORS before session**: preflight `OPTIONS` requests must be handled before session cookie processing.
- **Session before CSRF**: CSRF middleware reads `scope['session']` to get/set the CSRF token, so the session must be populated first.
- **CSRF last**: processes the request body after all other middleware can read from the request.

---

## Routing

Routes are defined explicitly in `routes.py` as Starlette `Route` and `Mount` objects:

```python
from starlette.routing import Route, Mount

article = ArticleController()

routes = [
    Route('/', homepage, methods=['GET'], name='page.home'),
    Mount('/articles', routes=[
        Route('/', article.index, methods=['GET'], name='articles.index'),
        Route('/{id:int}', article.show, methods=['GET'], name='articles.show'),
        Route('/', article.store, methods=['POST'], name='articles.store'),
    ]),
]
```

Key conventions:
- Always provide `methods=` to be explicit about allowed HTTP methods.
- Always provide `name=` for reverse routing in templates and redirects.
- Controllers are instantiated once globally, not per-request.

---

## Dependency Injection (`@inject`)

The `@inject()` decorator on controller methods automatically maps request data into function parameters. It reads the function signature **once at decoration time** (not per request) and injects values on each call.

### Resolution Order

For each parameter in the function signature (excluding `self` and `request`):

1. **`form` / `dict` annotation** → entire parsed request body (JSON or form data)
2. **Path parameters** → `request.path_params[name]`, with type casting from annotation
3. **Query parameters** → `request.query_params[name]`, with type casting from annotation
4. **Default value** → `param.default` if none of the above matched, or `None`

### How It Works

```python
from core.http.inject import inject

class ProductController:
    @inject()
    async def update(self, request, product_id: int, form: dict):
        # product_id: auto-cast from path param /products/{product_id}
        # form: entire request body as dict (JSON or form-encoded)
        ...
```

### Type Casting

Type coercion is applied only for simple types: `int`, `float`, `str`, `bool`. If a parameter has one of these annotations (e.g. `product_id: int`), `@inject` casts the raw string value. If casting fails (e.g. `int('abc')`), the parameter falls back to its default value or `None`.

Complex generic types (`list[int]`, `dict[str, Any]`, etc.) are **not** coerced — the raw value is passed as-is. Parse these manually from `request.json()` or `request.form()`.

### Form Data Source

`@inject` detects the content type automatically:
- `application/json` → `await request.json()`
- Everything else → `await request.form()` → converted to `dict`

If parsing fails (e.g. malformed JSON), the decorator returns a **400 Bad Request** response with `{"error": "Invalid request body"}` instead of silently proceeding with empty data. Type coercion failures on path and query parameters are logged as warnings and fall back to the parameter's default value.

---

## Error Handling

### Production Mode (`DEBUG=false`)

Two custom error handlers are registered:

**404 Not Found** — content-negotiated:
- If `Accept: application/json` → `{"error": "Not Found"}` with status 404
- Otherwise → renders `rootsystem/templates/404.html`

**500 Internal Server Error**:
- Logs the full exception with traceback via `nori.asgi` logger
- Renders `rootsystem/templates/500.html`

### Development Mode (`DEBUG=true`)

Starlette's built-in debug error pages are used, showing full tracebacks in the browser.

---

## Authentication Decorators

These decorators wrap controller methods and run **before** the method body:

| Decorator | Checks | On failure (JSON) | On failure (HTML) |
|-----------|--------|-------------------|-------------------|
| `@login_required` | `request.session['user_id']` exists | 401 Unauthorized | Redirect to `/login` |
| `@require_role('admin')` | `request.session['role']` matches | 403 Forbidden | Redirect to `/forbidden` |
| `@require_any_role('admin', 'editor')` | Role matches any | 403 Forbidden | Redirect to `/forbidden` |
| `@require_permission('articles.edit')` | Permission in session cache | 403 Forbidden | Redirect to `/forbidden` |
| `@token_required` | Valid JWT in `Authorization: Bearer` header | 401 Unauthorized | 401 Unauthorized |

- `admin` role bypasses all role and permission checks.
- Permissions must be loaded at login with `await load_permissions(request.session, user.id)`.
- `@token_required` stores the decoded payload in `request.state.token_payload`.

---

## Decoupling: Registry & Config

Nori 1.2.0 introduced a decoupled architecture to ensure the core remains agnostic to the application structure, facilitating seamless framework updates.

### 1. Model Registry (`core.registry`)

The core never imports models directly from the `models/` directory. Instead, models are registered at application startup and retrieved by name.

**Registration (`models/__init__.py`)**:
```python
from core.registry import register_model
from models.audit_log import AuditLog
from models.job import Job

register_model('AuditLog', AuditLog)
register_model('Job', Job)
```

**Retrieval (`core/audit.py`)**:
```python
from core.registry import get_model

AuditLog = get_model('AuditLog')
await AuditLog.create(...)
```

This prevents circular dependencies and allows the framework core to be replaced or updated without breaking the application logic.

### 2. Configuration Provider (`core.conf`)

Core modules access settings through a configuration provider instead of importing `settings.py` directly. This allows the core to be distributed as a standalone library.

**Initialization (`asgi.py`)**:
```python
import settings
from core.conf import configure
configure(settings)
```

**Usage (`core/auth/jwt.py`)**:
```python
from core.conf import config

secret = config.JWT_SECRET
```

---

## Background Tasks

Nori wraps Starlette's `BackgroundTask` with error logging:

```python
from core.tasks import background, run_in_background

# Create a task — pass it to a response's background= parameter
task = background(send_welcome_email, user.email)
return JSONResponse({'ok': True}, background=task)

# Or attach a task to an existing response
response = JSONResponse({'ok': True})
run_in_background(response, send_welcome_email, user.email)
return response
```

If the background callable raises an exception, the error is **logged** (not swallowed, not re-raised). The HTTP response has already been sent, so the user is not affected.

---

## Logging

```python
from core.logger import get_logger

log = get_logger('mymodule')  # Creates 'nori.mymodule' logger
log.info('User %d logged in', user_id)
```

### Configuration (.env)

| Var | Values | Default |
|-----|--------|---------|
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | `DEBUG` if `DEBUG=true`, else `INFO` |
| `LOG_FORMAT` | `text`, `json` | `text` |
| `LOG_FILE` | File path (optional) | None (stdout only) |

### JSON Format

When `LOG_FORMAT=json`, each log line is a JSON object with: `timestamp` (ISO 8601 UTC), `level`, `logger`, `message`, `exception` (if any), `request_id` (if set by RequestIdMiddleware).

---

## Settings Validation

`validate_settings()` runs at startup (called in the ASGI lifespan context) and checks:

- Database credentials are present for non-SQLite in production
- Template and static directories exist on disk
- `JWT_SECRET` differs from `SECRET_KEY` in production
- `JWT_SECRET` has minimum 32 characters (HMAC-SHA256 security)

In production (`DEBUG=false`), validation failures raise `RuntimeError` — the app will not start with unsafe configuration. In development, issues are returned as warning strings.
