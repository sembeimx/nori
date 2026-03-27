# Architecture

How Nori processes a request from the network socket to the response, including the middleware stack, dependency injection, and error handling.

---

## Request Lifecycle

Every HTTP request flows through this pipeline:

```
Client → Uvicorn (ASGI) → Middleware Stack → Router → Controller Method → Response
```

### Middleware Stack

Middleware is registered in `asgi.py`. Starlette wraps middleware in LIFO order, so the **last registered middleware runs first** during the request phase. Here is the execution order as the request enters:

```
Request ──→ CSRF
              ↓
           Session
              ↓
          CORS (if enabled)
              ↓
        Security Headers
              ↓
         Request ID
              ↓
          Application (Router → Controller)
              ↓
         Request ID
              ↓
        Security Headers
              ↓
          CORS (if enabled)
              ↓
           Session
              ↓
            CSRF
              ↓
Response ←──┘
```

### What Each Middleware Does

| Middleware | Module | Purpose |
|-----------|--------|---------|
| **RequestIdMiddleware** | `core.http.request_id` | Generates a UUID per request (or propagates incoming `X-Request-ID`). Stored in `request.state.request_id`. Added to every response as `X-Request-ID` header. Enables end-to-end tracing across logs and services. |
| **SecurityHeadersMiddleware** | `core.http.security_headers` | Injects security headers on every response: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `X-XSS-Protection: 1; mode=block`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy: camera=(), microphone=(), geolocation=()`, `Strict-Transport-Security` (HSTS, 1 year). Optional CSP if configured. |
| **CORSMiddleware** | `starlette.middleware.cors` | Only added if `CORS_ORIGINS` is set in `.env`. Handles `OPTIONS` preflight and adds `Access-Control-*` headers. Allows methods: GET, POST, PUT, PATCH, DELETE, OPTIONS. Allows headers: Content-Type, Authorization, X-CSRF-Token. Credentials: enabled. |
| **SessionMiddleware** | `starlette.middleware.sessions` | Creates and validates signed session cookies using `SECRET_KEY`. Populates `request.session` as a dict-like object. Required by CSRF, auth decorators, and flash messages. |
| **CsrfMiddleware** | `core.auth.csrf` | Validates CSRF tokens on state-changing methods (POST, PUT, DELETE, PATCH). Skips safe methods (GET, HEAD, OPTIONS) and JSON requests (`application/json`). Checks `X-CSRF-Token` header first, then `_csrf_token` form field. Auto-generates token if missing. Returns 403 on mismatch, 413 on oversized body (DoS protection, 10 MB limit). |

### Why This Order Matters

- **Request ID first** (outermost): ensures every log message — including middleware errors — has a trace ID.
- **Security headers early**: guarantees all responses get security headers, even on middleware failures.
- **CORS before session**: preflight `OPTIONS` requests must be handled before session cookie processing.
- **Session before CSRF**: CSRF middleware reads `scope['session']` to get/set the CSRF token, so the session must be populated first.
- **CSRF last** (innermost): processes the request body after all other middleware can read from the request.

---

## Routing

Routes are defined explicitly in `routes.py` as Starlette `Route` and `Mount` objects:

```python
from starlette.routing import Route, Mount

article = ArticleController()

routes = [
    Route('/', homepage, methods=['GET'], name='home'),
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

If a parameter has a type annotation (e.g. `product_id: int`), `@inject` attempts to cast the raw string value using the annotation as a callable. If casting fails (e.g. `int('abc')`), the parameter falls back to its default value or `None`.

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
