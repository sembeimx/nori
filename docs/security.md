# Security

Nori provides multiple layers of security — from HTTP headers and CSRF protection to data-level safeguards in the ORM and file upload pipeline. All security features are enabled by default and require no configuration to activate.

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
| `Strict-Transport-Security` | `max-age=31536000` (1 year) | Downgrade attacks (HSTS) |

Optional `Content-Security-Policy` (CSP) can be configured if needed.

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
- **JSON APIs**: Requests with `Content-Type: application/json` are exempt (browsers enforce CORS for cross-origin JSON requests)
- **Custom paths**: Configurable exempt paths

### Usage in Templates

```html
<form method="POST" action="/articles">
    {{ csrf_field(request.session) }}
    <input type="text" name="title" />
    <button type="submit">Create</button>
</form>
```

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

### Backends

| Backend | Config | Best for |
|---------|--------|----------|
| `memory` (default) | `THROTTLE_BACKEND=memory` | Single-process, development |
| `redis` | `THROTTLE_BACKEND=redis` + `REDIS_URL=redis://localhost:6379` | Multi-process, production clusters |

The Redis backend shares counters across Gunicorn workers and Docker replicas.

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

The client-declared `Content-Type` header must match the expected MIME for the extension. This catches simple mismatches (e.g. uploading a PNG with `Content-Type: image/jpeg`).

### Layer 3: Magic Byte Verification

The **actual file content** is inspected for known file signatures:

| Extension | Magic Bytes | Description |
|-----------|-------------|-------------|
| `jpg`/`jpeg` | `\xff\xd8\xff` | JPEG Start of Image |
| `png` | `\x89PNG\r\n\x1a\n` | PNG signature |
| `gif` | `GIF87a` or `GIF89a` | GIF versions |
| `pdf` | `%PDF` | PDF header |
| `webp` | `RIFF` | WebP container |

### Why Magic Bytes Matter

An attacker can trivially bypass extension and MIME checks:

1. Rename `malware.exe` → `malware.jpg`
2. Set `Content-Type: image/jpeg` in the upload form
3. Without magic byte verification, the file passes all checks

With magic byte verification, the actual file content is inspected. A PE executable starts with `MZ`, not `\xff\xd8\xff` — the upload is rejected with `UploadError: File content does not match expected format for '.jpg' (magic byte verification failed)`.

### Design Decision

Magic byte verification is implemented in **pure Python** (~15 lines) without external dependencies. This is intentional — `python-magic` requires `libmagic` (a C library, ~10 MB), which violates Nori's "Keep it Native" philosophy. The pure Python approach covers the most common file types (~90% of real-world uploads). Extensions without known signatures (SVG, CSV, etc.) skip this check gracefully.

---

## JWT Security

Nori implements JWT with HMAC-SHA256 in `core.auth.jwt`. Three safeguards protect token integrity:

### 1. Independent Secret

`JWT_SECRET` must be set separately from `SECRET_KEY` in production. If `JWT_SECRET` falls back to `SECRET_KEY`, a warning is logged and `validate_settings()` reports an error.

```text
# .env
JWT_SECRET=your-independent-jwt-secret-here-minimum-32-chars
```

### 2. Minimum Length Enforcement

`validate_settings()` enforces a minimum of **32 characters** for `JWT_SECRET` in production. Shorter secrets are rejected at startup:

```
Settings validation failed:
  - JWT_SECRET is too short (minimum 32 characters).
    Use: python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 3. Constant-Time Comparison

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
