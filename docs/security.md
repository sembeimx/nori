# Security

Nori provides multiple layers of security — from HTTP headers and CSRF protection to data-level safeguards in the ORM and file upload pipeline. All security features are enabled by default and require no configuration to activate.

Every security feature in Nori is enabled by default. We don't trust developers to remember to turn things on -- we trust them to turn things off when they have a reason.

---

## Security Headers

`SecurityHeadersMiddleware` injects the following headers on every HTTP response:

| Header | Value | Protects Against |
|--------|-------|-----------------|
| `X-Content-Type-Options` | `nosniff` | MIME-sniffing attacks |
| `X-Frame-Options` | `DENY` | Clickjacking |
| `X-XSS-Protection` | `1; mode=block` | Reflected XSS (legacy browsers) |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Information leakage via referrer |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` | Unauthorized device access |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` (1 year) | Downgrade attacks (HSTS) |
| `Content-Security-Policy-Report-Only` | A strict default policy (since v1.13.0) | XSS, content injection, exfiltration |

HSTS is enabled by default. To disable it (e.g., during development without HTTPS), pass `hsts=False` to `SecurityHeadersMiddleware` in `asgi.py`.

### Content Security Policy (CSP)

Since v1.13.0 Nori ships a sensible default CSP in **report-only** mode. Browsers evaluate the policy and log violations to the console (or a configured report endpoint) **without blocking content**, so existing pages render unchanged while you discover what would break under enforcement.

The default policy (`core.http.security_headers.DEFAULT_CSP`):

```
default-src 'self';
script-src 'self';
style-src 'self' 'unsafe-inline';
img-src 'self' data:;
font-src 'self' data:;
connect-src 'self';
frame-ancestors 'none';
base-uri 'self';
form-action 'self'
```

`'unsafe-inline'` for styles is included because Jinja templates routinely use inline style attributes. Scripts are kept strict (`'self'` only) — no inline `<script>` blocks, no `onclick=` handlers. The default is conservative on purpose; relax it only when you've observed which directives your templates actually need.

#### Migration path

1. **Stage 1 — observe** (default). Ship report-only, watch your browser console / report endpoint for violations. Real-world apps almost always need to relax `style-src` further or whitelist a CDN under `script-src` / `img-src`.
2. **Stage 2 — tighten**. Pass a custom `csp='...'` matching what your app actually needs.
3. **Stage 3 — enforce**. Flip `csp_report_only=False` to switch from `Content-Security-Policy-Report-Only` to `Content-Security-Policy`. Browsers now BLOCK violating content.

#### Configuration in `asgi.py`

```python
Middleware(
    SecurityHeadersMiddleware,
    csp='default',                    # default: ship Nori's DEFAULT_CSP. Pass a string to override.
    csp_report_only=True,             # default: report mode. Flip to False to enforce.
    csp_report_uri='/csp-violations', # default: None (browsers log to console only).
)
```

To **opt out entirely** (e.g., for an API-only service that doesn't render HTML): `csp=None` or `csp=False`.

#### Receiving violation reports

If you set `csp_report_uri='/csp-violations'`, browsers POST a JSON payload to that endpoint. A minimal handler:

```python
@inject()
async def report(self, request: Request, json: dict):
    log = get_logger('security.csp')
    log.warning('CSP violation: %s', json.get('csp-report', json))
    return JSONResponse({'received': True}, status_code=204)
```

Then route it: `Route('/csp-violations', csp.report, methods=['POST'])`. Make sure to exempt it from CSRF (browser-originated, no session) — the `core/auth/csrf.py` exempt list is the place.

---

## CSRF Protection

`CsrfMiddleware` validates CSRF tokens on all state-changing HTTP methods (POST, PUT, DELETE, PATCH).

### How it works

1. On the first request, the middleware auto-generates a CSRF token and stores it in `request.session['_csrf_token']`.
2. On state-changing requests, it checks for the token in:
   - `X-CSRF-Token` header (for AJAX/fetch requests)
   - `_csrf_token` form field (for HTML forms)
3. Comparison uses constant-time HMAC (`hmac.compare_digest`) to prevent timing attacks.
4. Mismatch returns **403 Forbidden**.
5. Oversized body (> 10 MB) returns **413 Request Entity Too Large** (DoS protection).

### Exempt from CSRF

- **Safe methods**: GET, HEAD, OPTIONS, TRACE
- **Custom paths**: Configurable exempt paths

### JSON clients

JSON requests are **not exempt**. The `Content-Type: application/json` header alone is not a safe CSRF defense — it relies on CORS being configured correctly, which is not a guarantee Nori can enforce. JSON clients (SPAs, fetch, axios) must send the token via the `X-CSRF-Token` header on every state-changing request.

### Usage in Templates

`csrf_field` and `csrf_token` are registered as Jinja2 globals — you can call them directly in any template without passing them from the controller:

```html
<form method="POST" action="/articles">
    {{ csrf_field(request.session)|safe }}
    <input type="text" name="title" />
    <button type="submit">Create</button>
</form>
```

- `csrf_field(request.session)` returns a full `<input type="hidden" ...>` tag — use `|safe` to render the HTML.
- `csrf_token(request.session)` returns the raw token string (useful for AJAX headers).

For AJAX requests:

```javascript
fetch('/articles', {
    method: 'POST',
    headers: {
        'X-CSRF-Token': '{{ csrf_token(request.session) }}',
        'Content-Type': 'application/json',
    },
    body: JSON.stringify({ title: 'Hello' }),
});
```

---

## Cross-Origin Resource Sharing (CORS)

Only activated if `CORS_ORIGINS` is set in `.env`. If omitted or empty, all cross-origin requests are denied (same-site policy).

```text
CORS_ORIGINS=http://localhost:3000,https://app.example.com
```

Configuration:
- **Methods**: GET, POST, PUT, PATCH, DELETE, OPTIONS
- **Headers**: Content-Type, Authorization, X-CSRF-Token
- **Credentials**: Enabled (cookies/sessions work cross-origin)

---

## Rate Limiting (`@throttle`)

Protects against brute-force, scraping, and DoS attacks. Limits are applied **per endpoint + per IP address** — blocking one endpoint doesn't affect others.

```python
from core.http.throttle import throttle

class AuthController:
    @throttle('5/minute')      # 5 attempts per minute
    async def login(self, request):
        ...

    @throttle('100/hour')      # API consumption limit
    async def get_report(self, request):
        ...
```

Returns **429 Too Many Requests** when the limit is exceeded (JSON or HTML based on `Accept` header).

### Rate-Limit Headers

The decorator adds rate-limit headers to **every response** (both allowed and blocked):

| Header | Description |
|--------|-------------|
| `X-RateLimit-Limit` | Maximum requests allowed in the window |
| `X-RateLimit-Remaining` | Requests remaining in the current window |
| `X-RateLimit-Reset` | Seconds until the window resets |

Clients can use these headers to implement backoff or display rate-limit status in the UI.

### Trusted Proxies (IP Spoofing Protection)

Rate limiting uses the client IP address as part of the key. When running behind a reverse proxy (Nginx, Cloudflare, ALB), the real client IP is in the `X-Forwarded-For` header. However, this header is **only trusted from known proxies** to prevent IP spoofing.

Configure trusted proxies in `.env`:

```text
TRUSTED_PROXIES=127.0.0.1,10.0.0.1
```

If `TRUSTED_PROXIES` is empty (default), `X-Forwarded-For` is ignored and the direct connection IP is used. This also affects the IP address recorded by the [audit logger](services.md#audit-logging-coreaudit).

The header is parsed **right-to-left**, skipping known proxies until the first untrusted hop is found — that's the real client. Taking the leftmost value would let any attacker inject an arbitrary IP (`X-Forwarded-For: 1.2.3.4`) and have it survive the proxy chain, since proxies append their source on the right but do not overwrite the spoofed prefix on the left.

### Backends

| Backend | Config | Best for |
|---------|--------|----------|
| `memory` (default) | `THROTTLE_BACKEND=memory` | Single-process, development |
| `redis` | `THROTTLE_BACKEND=redis` + `REDIS_URL=redis://localhost:6379` | Multi-process, production clusters |

The Redis backend shares counters across Gunicorn workers and Docker replicas.

---

## Queue Worker Module Allow-List

`push()` jobs are persisted as a `(func, args, kwargs)` tuple where `func` is a string of the form `'module.path:function_name'`. The worker resolves it via `importlib.import_module + getattr`. **Without restrictions, write access to the queue store (a SQL injection point reaching the `jobs` table, an unauthenticated Redis instance, or any breach of the persistence layer) becomes arbitrary code execution under the worker's privileges.**

Nori blocks this in three layers, each independently sufficient for the canonical `os:system` payload but stacked because real attackers will look for the gaps between them:

1. **Module allow-list (primary)** — the `mod_path` half of the spec is checked against `QUEUE_ALLOWED_MODULES` (`settings.py`, default `['modules.', 'services.', 'app.', 'tasks.']`) **before** `importlib.import_module` runs. Prefixes are normalized to require a trailing `.` so a name like `modules` does not accidentally match `modules_evil`. Anything outside the list is rejected with `PermissionError` and counts as a job failure — the existing retry/backoff and dead-letter path handles it, so a poisoned payload cannot stall the worker.
2. **Bare-identifier check on `func_name`** — the function half must match `^[A-Za-z_][A-Za-z0-9_]*$`. `getattr` does not recurse on dots, but rejecting `tasks:os.system` up front makes the contract obvious and removes a quirk to remember.
3. **Re-export defence on `func.__module__` (1.23+)** — after `getattr` resolves the callable, its `__module__` is re-checked against the same allow-list. Without this layer, an allow-listed `tasks/__init__.py` containing `from os import system` exposed `tasks:system` as a working RCE — the alias passed step 1 because its *import path* was inside the allow-list, even though the *function* came from `os`. The recheck refuses the call when the resolved `__module__` lands outside the allow-list.

This is defense in depth, not a replacement for store-level access controls (DB user grants, Redis AUTH/ACL).

See [Background Tasks → Security: module allow-list](background_tasks.md#security-module-allow-list) for configuration details, prefix normalization, and the full threat model.

---

## ORM: `protected_fields`

Models can define a `protected_fields` class attribute to prevent sensitive data from leaking through `to_dict()`.

### The Problem

Without `protected_fields`, a developer who forgets `exclude=` will accidentally expose sensitive data:

```python
user = await User.get(id=1)
return JSONResponse(user.to_dict())  # ⚠ Includes password_hash, tokens, etc.
```

### The Solution

```python
from tortoise import fields, Model
from core.mixins.model import NoriModelMixin

class User(NoriModelMixin, Model):
    protected_fields = ['password_hash', 'remember_token', 'two_factor_secret']

    id = fields.IntField(primary_key=True)
    username = fields.CharField(max_length=100)
    email = fields.CharField(max_length=255)
    password_hash = fields.CharField(max_length=255)
    remember_token = fields.CharField(max_length=255, default='')
    two_factor_secret = fields.CharField(max_length=255, default='')
```

Now `to_dict()` automatically excludes protected fields:

```python
user.to_dict()
# → {'id': 1, 'username': 'alice', 'email': 'alice@example.com'}
# password_hash, remember_token, two_factor_secret are excluded

user.to_dict(exclude=['email'])
# → {'id': 1, 'username': 'alice'}
# Both protected_fields AND explicit exclude are merged

user.to_dict(include_protected=True)
# → {'id': 1, 'username': 'alice', 'email': '...', 'password_hash': '...', ...}
# Force-include for internal/admin operations
```

### Key Behaviors

- **Backwards compatible**: Models without `protected_fields` work exactly as before.
- **Merged with `exclude`**: `protected_fields` and the `exclude=` parameter are combined.
- **Explicit opt-in**: `include_protected=True` is the only way to get protected fields in the output.

---

## Upload Security: Magic Byte Verification

File uploads are validated through three layers (see [Services](services.md) for full upload docs):

### Layer 1: Extension Check

Only extensions in `allowed_types` are accepted. A `.exe` file is rejected before any further processing.

### Layer 2: MIME Type Check

The client-declared `Content-Type` header must match the expected MIME for the extension. The base MIME type is extracted before comparison (e.g. `image/jpeg; charset=utf-8` is treated as `image/jpeg`), so charset parameters don't cause false rejections. Empty files (0 bytes) are also rejected at this stage.

### Layer 3: Magic Byte Verification

The **actual file content** is inspected for known file signatures:

| Extension | Magic Bytes | Description |
|-----------|-------------|-------------|
| `jpg`/`jpeg` | `\xff\xd8\xff` | JPEG Start of Image |
| `png` | `\x89PNG\r\n\x1a\n` | PNG signature |
| `gif` | `GIF87a` or `GIF89a` | GIF versions |
| `pdf` | `%PDF` | PDF header |
| `webp` | `RIFF` + `WEBP` at offset 8 | WebP container (full RIFF structure validated) |

### Why Magic Bytes Matter

Checking file extensions is security theater. An attacker renames `malware.exe` to `photo.jpg` and hopes you only check the name. Magic byte verification reads the actual file header -- it catches what extensions miss.

An attacker can trivially bypass extension and MIME checks:

1. Rename `malware.exe` → `malware.jpg`
2. Set `Content-Type: image/jpeg` in the upload form
3. Without magic byte verification, the file passes all checks

With magic byte verification, the actual file content is inspected. A PE executable starts with `MZ`, not `\xff\xd8\xff` — the upload is rejected with `UploadError: File content does not match expected format for '.jpg' (magic byte verification failed)`.

### Design Decision

Magic byte verification is implemented in **pure Python** (~15 lines) without external dependencies. This is intentional — `python-magic` requires `libmagic` (a C library, ~10 MB), which violates Nori's "Keep it Native" philosophy. The pure Python approach covers the most common file types (~90% of real-world uploads). Extensions without known signatures (SVG, CSV, etc.) skip this check gracefully.

---

## JWT Security

Nori implements JWT with HMAC-SHA256 in `core.auth.jwt`. Five safeguards protect token integrity:

### 1. Algorithm Validation

`verify_token()` explicitly decodes the JWT header and rejects any token where `alg` is not `HS256`. This defends against algorithm confusion attacks (e.g. `alg: none`).

### 2. Clock Skew Tolerance

Token expiration includes a **10-second leeway** to account for clock differences in distributed systems. A token expired 5 seconds ago will still be accepted; one expired 15 seconds ago will not.

### 3. Independent Secret

`JWT_SECRET` must be set separately from `SECRET_KEY` in production. If `JWT_SECRET` falls back to `SECRET_KEY`, a warning is logged and `validate_settings()` reports an error.

```text
# .env
JWT_SECRET=your-independent-jwt-secret-here-minimum-32-chars
```

### 4. Minimum Length Enforcement

`validate_settings()` enforces a minimum of **32 characters** for `JWT_SECRET` in production. Shorter secrets are rejected at startup:

```
Settings validation failed:
  - JWT_SECRET is too short (minimum 32 characters).
    Use: python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 5. Constant-Time Comparison

Token signatures are verified using `hmac.compare_digest()`, which prevents timing attacks that could otherwise be used to forge valid signatures byte by byte.

### Generate a Secure Secret

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

This produces a 43-character URL-safe string with 256 bits of entropy.

---

## Password Hashing

`core.auth.security.Security` provides PBKDF2-HMAC-SHA256 with 100,000 iterations:

```python
from core.auth.security import Security

hashed = Security.hash_password('my_password')
# → 'pbkdf2_sha256$100000$random_salt$derived_hash'

Security.verify_password('my_password', hashed)  # → True
Security.verify_password('wrong', hashed)         # → False (constant-time)
```

- **Salt**: Random per password (stored in the hash string).
- **Comparison**: Constant-time via `hmac.compare_digest`.
- **Format**: `algorithm$iterations$salt$hash` — self-describing, no external state needed.

---

## Session Revocation (Session Version Guard)

Starlette's `SessionMiddleware` issues signed cookies — the signature prevents tampering, not theft. Once the cookie leaves the user's browser (XSS, malware, third-party JS leak, physical access), the attacker has the same authority as the user until the cookie's `max_age` expires. There is no native revocation channel.

The `core.auth.session_guard` module plugs this hole with a per-user integer counter. At login the project copies the user's current version into the session. On every gated request, the framework compares the session version against the canonical version in the database. Bumping the version (`invalidate_session(user_id)`) invalidates every cookie carrying a stale version on the next gated request, atomically across all in-flight sessions for that user.

This feature is **opt-in**. Existing projects upgrading to v1.33+ see no behavior change until they explicitly enable it.

### Threat model

The guard defends against a stolen / leaked session cookie continuing to authenticate after:

- the user changed their password,
- an admin deactivated or suspended the account,
- the user clicked "log out everywhere",
- a security event triggered a forced re-login.

It does **not** defend against:

- A compromised cookie used immediately (within the request itself — there's nothing to revoke yet).
- An attacker who already has the password and can re-authenticate.
- An XSS exploit that can read AND modify the session, including `session_version`.

### Enabling the feature

**1. Add the column to your User model:**

```python
# rootsystem/application/models/user.py
from tortoise import fields
from core.mixins import NoriModelMixin
from tortoise.models import Model

class User(NoriModelMixin, Model):
    session_version = fields.IntField(default=0)
    # ... existing fields ...
```

**2. Run the migration:**

```bash
python3 nori.py migrate:make 'add session_version to user'
python3 nori.py migrate:upgrade
```

**3. Enable the check in settings:**

```python
# settings.py
SESSION_VERSION_CHECK = True
```

**4. Populate `session_version` at login:**

```python
async def login(self, request, form):
    user = await User.get_or_none(email=form['email'])
    # ... password verification ...
    request.session['user_id'] = user.id
    request.session['session_version'] = user.session_version
    # ... rest of login flow ...
```

**5. Restart the server.** If `SESSION_VERSION_CHECK = True` and the column is missing, Nori raises `RuntimeError` at boot with the exact migration to apply — silent degradation is intentionally NOT supported.

### Revoking sessions

```python
from core.auth.session_guard import invalidate_session

# From a request handler — audit event captures the actor:
async def logout_everywhere(self, request):
    user_id = int(request.session['user_id'])
    await invalidate_session(user_id, request=request)
    request.session.clear()
    return RedirectResponse('/login', status_code=302)

# From admin / CLI tooling — pass request=None to skip the audit
# event (the caller is responsible for its own forensic trail):
await invalidate_session(user_id_being_revoked, request=None)
```

### Failure modes

When **both** the cache and the database are unreachable in the same request, the gate cannot determine whether the session is still valid. The configured fail mode decides what to do:

- `SESSION_VERSION_FAIL_MODE = 'open'` (default): allow the request, write `session_guard.fail_open` to the audit log. Right for SaaS / blogs / internal tools — a brief storage hiccup should not 401 every authenticated request.
- `SESSION_VERSION_FAIL_MODE = 'closed'`: deny the request (401 / redirect), write `session_guard.fail_closed`. Right for finance / healthcare / compliance contexts where a brief denial is preferable to a brief auth bypass.

A **process-local circuit breaker** protects against sustained outages independently of the configured fail mode. Once `SESSION_VERSION_CIRCUIT_THRESHOLD` consecutive storage failures land within `SESSION_VERSION_CIRCUIT_WINDOW` seconds, the breaker forces fail-closed for `SESSION_VERSION_CIRCUIT_OPEN_DURATION` seconds regardless of the configured mode. The breaker state lives entirely in process memory — deliberately NOT in the cache, since the cache is the resource we cannot rely on at the moment we need to make this decision.

| Setting | Default | Description |
| --- | --- | --- |
| `SESSION_VERSION_CHECK` | `False` | Master opt-in. When `False` the gate is a no-op. |
| `SESSION_VERSION_FAIL_MODE` | `'open'` | `'open'` or `'closed'` — what to do when both stores fail. |
| `SESSION_VERSION_CIRCUIT_THRESHOLD` | `50` | Consecutive failures before the breaker opens. |
| `SESSION_VERSION_CIRCUIT_WINDOW` | `60` | Sliding window (seconds) for the failure counter. |
| `SESSION_VERSION_CIRCUIT_OPEN_DURATION` | `30` | Seconds the breaker stays open before retrying. |

### Audit events

Every denial path writes a structured audit event to `core.audit` so security teams have a forensic trail without parsing logs:

| Action | When |
| --- | --- |
| `session.invalidated` | `invalidate_session(user_id, request=...)` was called. |
| `session_guard.revoked` | Version mismatch — the session was bumped between login and now. `changes` contains `session_v` and `live_v`. |
| `session_guard.user_deleted` | DB returned `None` for the user — row was hard-deleted while sessions were live. |
| `session_guard.fail_open` | Both cache and DB failed; configured mode allowed the request. |
| `session_guard.fail_closed` | Both cache and DB failed; configured mode denied the request. |
| `session_guard.circuit_open` | Process-local circuit breaker is tripped — sustained outage detected, forcing fail-closed. |

### Tradeoffs

- **Per-request cache hit.** Every gated request reads `session_guard:{user_id}:version` from the cache. With Redis this is sub-millisecond on a warm connection; with the in-memory backend it's effectively free. For the highest-volume routes (10k+ rps), measure before enabling.
- **DB read on cache miss.** Cache evictions cause one extra DB round-trip per request until the cache repopulates. The `cache_set` after the DB read makes this self-healing; subsequent requests hit the cache again.
- **Worker-local breakers.** Each process tracks its own breaker. With N workers, a cache outage trips `threshold` failures per worker independently. There is no shared coordination because the only durable shared state available is the cache — the resource we cannot rely on at the moment we need it.
- **Cookie storage of `session_version` is integer.** Sessions remain compact. The cookie size grows by a few bytes (the integer + JSON key) per session.

---

This page looks long. It's not. It's the minimum for a production web application. Security isn't a feature you bolt on -- it's the foundation everything else stands on.

## Security Checklist

When building with Nori, ensure:

- [ ] `SECRET_KEY` is set to a strong random value in production
- [ ] `JWT_SECRET` is independent from `SECRET_KEY` and at least 32 characters
- [ ] `DEBUG=false` in production (disables debug error pages)
- [ ] `CORS_ORIGINS` only lists trusted domains (or is empty for same-site)
- [ ] State-changing actions use POST/PUT/DELETE, never GET
- [ ] All forms include `{{ csrf_field(request.session) }}`
- [ ] Models with sensitive fields define `protected_fields`
- [ ] File upload `allowed_types` is restrictive (don't allow `*`)
- [ ] Rate limiting is applied to authentication and expensive endpoints
- [ ] `TRUSTED_PROXIES` is configured if running behind a reverse proxy
- [ ] `QUEUE_ALLOWED_MODULES` covers your job locations (don't widen unnecessarily)
- [ ] `SESSION_VERSION_CHECK` is enabled if your app supports admin-initiated session revocation
