# Middleware

Nori uses ASGI middleware to process every HTTP request and response. Middleware runs before your controller code and after it — a pipeline that adds security headers, manages sessions, validates CSRF tokens, and traces requests across services.

---

## Middleware Stack

Middleware is registered in `asgi.py` as an ordered list. Starlette wraps them so the **first in the list runs first** on the way in and **last on the way out**:

```
Request ──→ RequestIdMiddleware
               ↓
         SecurityHeadersMiddleware
               ↓
           CORSMiddleware (if enabled)
               ↓
            SessionMiddleware
               ↓
             CsrfMiddleware
               ↓
           Your Controller
               ↓
             CsrfMiddleware
               ↓
            SessionMiddleware
               ↓
           CORSMiddleware (if enabled)
               ↓
         SecurityHeadersMiddleware
               ↓
          RequestIdMiddleware
               ↓
Response ←──┘
```

### Registration

```python
# asgi.py
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from core.auth.csrf import CsrfMiddleware
from core.http.request_id import RequestIdMiddleware
from core.http.security_headers import SecurityHeadersMiddleware

middleware = [
    Middleware(RequestIdMiddleware),
    Middleware(SecurityHeadersMiddleware),
    Middleware(SessionMiddleware, secret_key=settings.SECRET_KEY, https_only=not settings.DEBUG),
    Middleware(CsrfMiddleware),
]

if settings.CORS_ORIGINS:
    middleware.insert(1, Middleware(CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_methods=settings.CORS_ALLOW_METHODS,
        allow_headers=settings.CORS_ALLOW_HEADERS,
        allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    ))
```

### Why This Order

Middleware order is not arbitrary. Each position is deliberate:

- **RequestId first**: every log line — including middleware errors — gets a trace ID.
- **SecurityHeaders early**: all responses get security headers, even on middleware failures.
- **CORS before Session**: preflight `OPTIONS` requests must be handled before session cookie processing.
- **Session before CSRF**: the CSRF middleware reads `scope['session']` to get/set the token, so the session must be populated first.
- **CSRF last**: processes the request body after all other middleware have had their turn.

---

## Built-in Middleware

### RequestIdMiddleware

**Module**: `core.http.request_id`

Assigns a unique UUID to each HTTP request for end-to-end tracing. The ID is available in your controller, in log output, and in the response headers.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `header_name` | `str` | `'x-request-id'` | Header name to read/write |
| `trust_incoming` | `bool` | `True` | Accept `X-Request-ID` from the client instead of generating a new one |

**Behavior**:

1. If `trust_incoming=True` and the request includes an `X-Request-ID` header, that value is reused (useful for tracing across a reverse proxy or microservices).
2. Otherwise, a new `uuid4` is generated.
3. The ID is stored in `request.state.request_id` and added to the response as `X-Request-ID`.

**Access in controllers**:

```python
async def show(self, request: Request):
    request_id = request.state.request_id
    log.info("Processing request %s", request_id)
```

**Disable incoming trust** (e.g., if clients should not control the trace ID):

```python
Middleware(RequestIdMiddleware, trust_incoming=False),
```

---

### SecurityHeadersMiddleware

**Module**: `core.http.security_headers`

Injects security headers on every HTTP response. Headers are pre-encoded at startup for zero per-request overhead.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `headers` | `dict` | See below | Custom headers that override the defaults |
| `hsts` | `bool` | `True` | Enable `Strict-Transport-Security` |
| `hsts_max_age` | `int` | `31536000` (1 year) | HSTS max-age in seconds |
| `csp` | `str \| None` | `None` | Content-Security-Policy value (not sent if `None`) |

**Default headers**:

| Header | Value | Protects Against |
|--------|-------|-----------------|
| `X-Content-Type-Options` | `nosniff` | MIME-sniffing attacks |
| `X-Frame-Options` | `DENY` | Clickjacking |
| `X-XSS-Protection` | `1; mode=block` | Reflected XSS (legacy browsers) |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Information leakage via referrer |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` | Unauthorized device access |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` | Protocol downgrade attacks |

**Add a Content Security Policy**:

```python
Middleware(SecurityHeadersMiddleware,
    csp="default-src 'self'; script-src 'self' https://cdn.example.com",
),
```

**Disable HSTS** (for development without HTTPS):

```python
Middleware(SecurityHeadersMiddleware, hsts=False),
```

**Override a default header**:

```python
Middleware(SecurityHeadersMiddleware,
    headers={'X-Frame-Options': 'SAMEORIGIN'},
),
```

---

### SessionMiddleware

**Module**: `starlette.middleware.sessions` (Starlette built-in)

Creates and validates signed session cookies using `SECRET_KEY`. Populates `request.session` as a dict-like object.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `secret_key` | `str` | `settings.SECRET_KEY` | Key for signing session cookies |
| `https_only` | `bool` | `not settings.DEBUG` | Only send cookie over HTTPS |

Sessions are required by CSRF protection, authentication decorators (`@login_required`, `@role_required`), and flash messages. In production (`DEBUG=False`), the cookie is marked `Secure` so it is never sent over plain HTTP.

---

### CsrfMiddleware

**Module**: `core.auth.csrf`

Validates CSRF tokens on all state-changing HTTP methods (POST, PUT, DELETE, PATCH). Full details in [Security](security.md#csrf-protection).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `exempt_paths` | `set \| None` | `None` | Paths to skip CSRF validation |

**Key behaviors**:

- **Token generation**: auto-generates a token into `session['_csrf_token']` on the first request.
- **Token lookup**: checks `X-CSRF-Token` header first, then `_csrf_token` form field (both URL-encoded and multipart).
- **Safe methods**: GET, HEAD, OPTIONS, TRACE are always exempt.
- **JSON exempt**: requests with `Content-Type: application/json` skip CSRF (browsers enforce CORS for cross-origin JSON).
- **Body size limit**: rejects bodies larger than 10 MB with 413 (DoS protection).
- **Constant-time comparison**: uses `hmac.compare_digest` to prevent timing attacks.

**Exempt specific paths** (e.g., a webhook endpoint):

```python
Middleware(CsrfMiddleware, exempt_paths={'/webhooks/stripe', '/webhooks/github'}),
```

**Template helpers** (registered as Jinja2 globals):

```html
<!-- Full hidden input -->
{{ csrf_field(request.session)|safe }}

<!-- Raw token for AJAX -->
{{ csrf_token(request.session) }}
```

---

### CORSMiddleware

**Module**: `starlette.middleware.cors` (Starlette built-in)

Only activated if `CORS_ORIGINS` is set in `.env`. If omitted or empty, all cross-origin requests are denied (same-site policy).

```text
# .env
CORS_ORIGINS=http://localhost:3000,https://app.example.com
```

| Setting | Default |
|---------|---------|
| `CORS_ORIGINS` | *(empty — CORS disabled)* |
| `CORS_ALLOW_METHODS` | `GET, POST, PUT, PATCH, DELETE, OPTIONS` |
| `CORS_ALLOW_HEADERS` | `Content-Type, Authorization, X-CSRF-Token` |
| `CORS_ALLOW_CREDENTIALS` | `True` |

---

## Rate Limiting (`@throttle`)

Rate limiting in Nori is not a stack middleware — it is a **per-endpoint decorator**. This gives you fine-grained control: different limits on different endpoints instead of a blanket rule.

```python
from core.http.throttle import throttle

class AuthController:
    @throttle('5/minute')
    async def login(self, request: Request):
        ...

    @throttle('100/hour')
    async def api_data(self, request: Request):
        ...
```

Full documentation: [Security — Rate Limiting](security.md#rate-limiting-throttle).

---

## Writing Custom Middleware

Nori uses raw ASGI middleware. No base class required — just a class with `__init__` and `__call__`:

```python
class TimingMiddleware:
    """Adds a Server-Timing header to every response."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)

        import time
        start = time.perf_counter()

        async def send_with_timing(message):
            if message['type'] == 'http.response.start':
                elapsed = time.perf_counter() - start
                headers = list(message.get('headers', []))
                headers.append((
                    b'server-timing',
                    f'total;dur={elapsed * 1000:.1f}'.encode('latin1'),
                ))
                message = {**message, 'headers': headers}
            await send(message)

        await self.app(scope, receive, send_with_timing)
```

### Registering Custom Middleware

Add it to the `middleware` list in `asgi.py`:

```python
from core.http.timing import TimingMiddleware

middleware = [
    Middleware(RequestIdMiddleware),
    Middleware(TimingMiddleware),          # ← add here
    Middleware(SecurityHeadersMiddleware),
    Middleware(SessionMiddleware, secret_key=settings.SECRET_KEY, https_only=not settings.DEBUG),
    Middleware(CsrfMiddleware),
]
```

### ASGI Middleware Pattern

Every ASGI middleware follows the same structure:

1. **`__init__(self, app, ...)`** — receives the next app in the chain and any configuration parameters.
2. **`async __call__(self, scope, receive, send)`** — called for every connection (HTTP, WebSocket, lifespan).
3. **Guard on scope type** — always check `scope['type'] != 'http'` and pass through non-HTTP scopes unchanged.
4. **Wrap `send` or `receive`** — to modify the response or request, wrap the `send` or `receive` callables.
5. **Call `self.app(scope, receive, send)`** — forward to the next middleware or the application.

### Tips

- **Pre-encode headers** in `__init__` instead of encoding on every request (see `SecurityHeadersMiddleware` for the pattern).
- **Non-HTTP scopes**: always pass WebSocket and lifespan scopes through untouched unless you specifically need to handle them.
- **Order matters**: place your middleware at the right position in the stack. If it needs session data, it must come after `SessionMiddleware`.
