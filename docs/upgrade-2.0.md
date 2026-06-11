# Upgrading to Nori v2.0.0

Nori v2.0.0 replaces the session-bound CSRF synchronizer token with an OWASP **signed double-submit cookie**. The change is stateless, requires no database migration, and only needs mechanical template updates plus an optional settings block.

---

## What changed (breaking)

| Area | v1.x behavior | v2.0.0 behavior |
|------|---------------|-----------------|
| CSRF token source | `session['_csrf_token']` set on GET | Per-visitor signed cookie `{nonce}.{sig}` issued via response `Set-Cookie` |
| Template helper signature | `csrf_field(request.session)` | `csrf_field(request)` |
| Token helper signature | `csrf_token(request.session)` | `csrf_token(request)` |
| Form body cap default | 1 MiB | **10 MB** |
| Cached form pages | Broke when served to a second visitor | Fixed — JS shim supplies the visitor's own cookie value |

---

## Quick path

1. **Bump** to Nori v2.0.0.
2. **Find-and-replace** in your templates (see commands below).
3. **Include the JS shim** on any page served from `cache_response` that submits forms (automatic if you extend the starter `base.html`).
4. **Review settings** — all `CSRF_COOKIE_*` settings have safe defaults; override only if needed.
5. **Verify** — submit a form on a cached page from two different browsers; both must succeed without a 403.

---

## Step 2 — Template find-and-replace

Replace all `csrf_field(request.session)` and `csrf_token(request.session)` calls with the new `request`-based signature:

```bash
# Find affected templates
rg -l 'csrf_field\(request\.session\)|csrf_token\(request\.session\)' templates/

# Replace in one pass (requires sd — install with: cargo install sd)
rg -l 'csrf_field\(request\.session\)|csrf_token\(request\.session\)' templates/ \
  | xargs sd 'csrf_(field|token)\(request\.session\)' 'csrf_$1(request)'
```

The replacement is purely mechanical — no logic change, only the argument type changes from `session dict` to `request object`.

---

## Step 3 — JS shim

The JS shim (`static/js/csrf.js`) reads the visitor's own CSRF cookie and writes it into the hidden `_csrf_token` field before every form submit. This is what makes cached form pages work correctly.

**If you extend the starter `base.html`**, the shim is already included — no action needed.

**If you use a custom base layout**, add this snippet before `</body>` on any page that (a) is served from `cache_response` AND (b) submits a POST form:

```html
<!-- Nori CSRF shim: before submit, copies this visitor's own CSRF cookie value into the
     hidden _csrf_token field and sets X-CSRF-Token on fetch/XHR, so forms on cached pages
     submit successfully even though the cached HTML carries a stranger's stale token. -->
<script src="/static/js/csrf.js" defer></script>
```

Pages that are never cached work without the shim (the server renders the correct masked value directly from the visitor's cookie).

---

## Step 4 — Settings (optional)

All `CSRF_COOKIE_*` settings default safely. Override in `settings.py` only if needed:

```python
# settings.py — v2.0.0 CSRF cookie settings (all are optional; defaults shown)
CSRF_COOKIE_NAME     = "csrftoken"        # or "__Host-csrftoken" for single-host HTTPS
CSRF_COOKIE_SECURE   = not DEBUG          # True in production
CSRF_COOKIE_SAMESITE = "Lax"             # "Strict" for same-site-only forms
CSRF_COOKIE_HTTPONLY = False             # MUST stay False — the JS shim reads document.cookie
CSRF_COOKIE_PATH     = "/"
# CSRF_COOKIE_MAX_AGE = None            # session cookie by default; set to int seconds if needed
```

**`__Host-` prefix recommendation.** For single-host HTTPS deployments, set `CSRF_COOKIE_NAME = "__Host-csrftoken"`. This enforces `Secure`, `Path=/`, and no `Domain` at the browser level, closing the subdomain cookie-injection attack vector. Do not use `__Host-` on multi-subdomain deployments or plain HTTP — the browser will silently reject the cookie.

**Persistent cache backend and cookie name changes.** If you change `CSRF_COOKIE_NAME` on a deployment using a **persistent Redis cache backend**, you must flush the cache after deploying. Cached pages embed `window.NORI_CSRF_COOKIE_NAME` (rendered by `base.html` from config). Until the cache is flushed, visitors served a stale cached page will look for the old cookie name — the shim will not find the new cookie and forms will 403.

---

## What you do NOT need to do

- **No DB migration** — the change is stateless. There is no new table or column.
- **No controller changes** — only templates and (optionally) settings.
- **No manual session cleanup** — old `_csrf_token` keys in existing sessions are ignored by the new middleware and expire naturally with the session.

---

## Migration checklist

- [ ] All `csrf_field(request.session)` / `csrf_token(request.session)` calls replaced with `csrf_field(request)` / `csrf_token(request)`.
- [ ] CSRF shim included on all pages served from `cache_response` that submit forms (or `base.html` extended).
- [ ] `CSRF_COOKIE_HTTPONLY` is `False` (or unset — default is `False`).
- [ ] In production, `CSRF_COOKIE_SECURE` is `True` and the site is HTTPS.
- [ ] A form on a `cache_response` page submits successfully from a second browser/visitor.

---

## Verification

Submit a form on a page decorated with `@cache_response` from two different browsers (or two different incognito sessions). Both submissions must return 200, not 403. The first visit warms the cache; the second visit receives the cached page body but a fresh per-visitor `Set-Cookie` from the middleware's send-wrapper — the shim reads that cookie and writes it into the form field before submission.
