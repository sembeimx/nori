# Nori Developer Standards & AI Protocol

This document defines the coding standards, architectural patterns, and implementation protocols for the Nori framework. Developers and automated workflows MUST adhere to these rules to ensure consistency, security, and maintainability.

---

## 1. Core Philosophy
1. **Keep it Native**: The core (`core.*`) must use no external libraries for Auth, JWT, Validation, Mail dispatch, Storage dispatch, or Tasks. Optional service drivers (`services/*`) may use external libraries for backend integrations (e.g., S3, Resend, Meilisearch).
2. **Decoupled by Design**: The core is agnostic to the application. Use `core.registry` for model access and `core.conf` for configuration. Never import `settings.py` or application models within `core/`.
3. **Security by Default**: CSRF is mandatory, passwords are hashed with PBKDF2, and sensitive fields are protected in models.
4. **Convention over Configuration**: Follow the established directory structure and naming patterns without "magic" auto-discovery.

---

## 2. Naming & Coding Conventions
- **Controllers**: `PascalCase` with `Controller` suffix (e.g., `UserController`). Methods are `async snake_case`.
- **Models**: `PascalCase` (e.g., `User`). Tables are plural (e.g., `users`).
- **Routes**: Dot-notation for names (e.g., `articles.show`). Explicit `methods=` are mandatory.
- **Templates**: Grouped in folders matching the module name (e.g., `templates/auth/login.html`).
- **Type Hints**: Mandatory for all function signatures. Use `from __future__ import annotations`.

---

## 3. Implementation Workflow (Nori 1.2+)
When adding a new feature or module, follow these steps IN ORDER:

1. **Model**: Define fields in `models/name.py`. Inherit from `NoriModelMixin`.
2. **Register**: Import the model in `rootsystem/application/models/__init__.py` AND call `register_model('Name', Name)`.
3. **Migrate**: `python3 nori.py migrate:make desc` -> `python3 nori.py migrate:upgrade`.
4. **Controller**: Create class in `modules/name.py`. Use `@inject()` and `validate()`.
5. **Routes**: Define explicit `Route` or `Mount` in `routes.py` with a unique `name`.
6. **Templates**: Create Jinja2 views. Use `{{ csrf_field(request)|safe }}` for POST forms.
7. **Verify**: Run `pytest tests/` and ensure the new logic is covered.

---

## 4. Master Boilerplates

### Controller Method
```python
@inject()
async def store(self, request: Request, form: dict):
    errors = validate(form, {'title': 'required|min:3'})
    if errors:
        return templates.TemplateResponse(request, 'create.html', {'errors': errors})
    # item = await MyModel.create(**form)
    flash(request, 'Created!')
    return RedirectResponse(url=request.url_for('my.index'), status_code=302)
```

### Model with Protection
```python
class User(NoriModelMixin, Model):
    protected_fields = ['password_hash', 'token'] # Auto-excluded from to_dict()
    # ... fields ...
```

---

## 5. Technical Quick Reference

### Validation Rules (`validate`)
- `required`, `email`, `numeric`, `matches:field`, `in:a,b`.
- `min:N`, `max:N`, `min_value:N`, `max_value:N`.
- `url`, `date`, `confirmed`, `nullable`, `array`, `regex:pattern`.
- `unique:table,column` (async — requires `validate_async()`).
- `file`, `file_max:2mb`, `file_types:jpg,png`.

### Database Mixins
- **`NoriSoftDeletes`**: Inherit from this instead of `Model` for logical deletion (`deleted_at`). It already extends `Model` — do not inherit both.
- **`NoriTreeMixin`**: For recursive hierarchies (requires `parent` ForeignKey).

### Background Logic
- **`background(func, *args)`**: Volatile, in-process task.
- **`push(func_path, *args)`**: Persistent, queued task (requires `python3 nori.py queue:work`). `func_path` must match a prefix in `QUEUE_ALLOWED_MODULES` (`settings.py`, defaults to `modules.`, `services.`, `app.`, `tasks.`) — paths outside the allow-list are rejected before import to block RCE via tampered queue payloads.

---

## 6. Security Mandates

These are quick reference reminders. The full catalog of bug classes (with CWE links, fix recipes, detector maturity, and coverage by area) lives in [INVARIANTS.md](./INVARIANTS.md) — read that file before shipping any security-relevant change.

- **POST only**: All state-changing actions (Logout, Delete, Update) MUST be `POST`.
- **Audit Logging**: Use `audit(request, action, model_name, record_id)` for sensitive operations.
- **Serialization**: Always use `.to_dict()` to leverage `protected_fields` safety. See [INV-008](./INVARIANTS.md#inv-008-serializers-must-respect-protected_fields).
- **Cache atomicity**: Use `cache_incr` or `cache_atomic_update` — never `cache_get + cache_set` for read-modify-write. See [INV-001](./INVARIANTS.md#inv-001-cache-read-modify-write-must-be-atomic-toctou).
- **Async I/O hygiene**: Wrap sync disk I/O and heavy CPU in `asyncio.to_thread`. See [INV-002](./INVARIANTS.md#inv-002-sync-work-must-not-block-the-asyncio-event-loop).
- **Connection reuse**: One module-level `httpx.AsyncClient` per service driver. See [INV-021](./INVARIANTS.md#inv-021-httpx-clients-must-be-reused-per-service-driver).
- **Optional spec fields**: `payload.get('jti')`, never `payload['jti']`. See [INV-007](./INVARIANTS.md#inv-007-jwtoauth-optional-claims-must-be-accessed-defensively).
- **Queue payloads**: `func_path` must pass `QUEUE_ALLOWED_MODULES` allow-list. See [INV-003](./INVARIANTS.md#inv-003-queue-worker-func_path-must-pass-allow-list-check-rce-defense).
- **Session revocation**: All session-aware decorators (`login_required`, `require_role`, `require_any_role`, `require_permission`) check `session_version` against the live counter. See [INV-016](./INVARIANTS.md#inv-016-session-revocation-must-work-end-to-end-active-user-gate--version-counter).
- **CSRF cookie**: Must be a signed structure `{nonce}.{sig}` (HMAC-SHA256). Bare-nonce double-submit is rejected. `cache_response` must never cache `Set-Cookie`. See [INV-030](./INVARIANTS.md#inv-030-csrf-cookie-must-be-a-signed-structure-set-cookie-must-never-be-cached).

---

## 7. Operational Pitfalls (for framework changes)

Code-side bug classes (TOCTOU, sync I/O, CWD-relative paths, docs↔code coherence, etc.) are in [INVARIANTS.md](./INVARIANTS.md). This section covers infra and deploy traps that do not fit the catalog shape.

### Hosting and docs deploys
- `nori.sembei.mx` runs on **Firebase Hosting**, not a VPS. Deploy is automatic via `.github/workflows/deploy-docs.yml` on every push to `main` that touches `docs/**` or `mkdocs.yml`. No manual `firebase deploy` is needed.
- The version badge in the docs sidebar is **client-side JavaScript** — the GitHub repo widget queries the API at page load. When it looks stale after a release, the fix is browser cache (hard reload, or unregister the service worker). Re-running the deploy workflow will NOT update it.
- Verify the actual host with `dig +short nori.sembei.mx` before assuming. Memory of past deploys can be stale.
- MkDocs publishes any `.md` file inside `docs/` even if not listed in `nav:` — direct URL works. Internal-only docs (such as [INVARIANTS.md](./INVARIANTS.md)) MUST live outside `docs/` to stay private.

### Releases and the installer
- `gh release create` → `releases/latest` API has a ~30-second indexing lag. The installer (`docs/install.py`) hits `releases/latest` by default, so the first install within ~1 minute of a release may pull the previous version. For testing right after release, pass `--version VX.Y.Z` to skip the latest endpoint.
- Always verify a release end-to-end with the installer (real `curl ... | python3 -`) before considering it shipped.
- Installer integrity contract: see [INV-025](./INVARIANTS.md#inv-025-installer-must-verify-checksum-of-downloaded-archive).

### CLI subprocess scripts (`core/cli.py`)
- See [INV-026](./INVARIANTS.md#inv-026-cli-subprocess-scripts-must-call-configuresettings-before-importing-user-code) for the `configure(settings)` bootstrap requirement.
- See [INV-027](./INVARIANTS.md#inv-027-file-and-module-path-resolution-must-be-cwd-independent) for CWD-independent path resolution.
- For aerich subprocesses, use `env=_quiet_env()` to suppress the `Module "X" has no models` RuntimeWarning. The same warning is filtered in-process via `core/__init__.py`.

### Repo-state lints
- See [INV-028](./INVARIANTS.md#inv-028-repo-state-itself-can-be-a-bug-ship-time-invariants).

### Configurable settings defaults
- See [INV-029](./INVARIANTS.md#inv-029-new-settings-must-default-via-configgetkey-default).

### Docs↔code coherence
- See [INV-015](./INVARIANTS.md#inv-015-docs-and-code-must-stay-coherent-manual-review-on-high-leverage-files) for the high-leverage file list and the per-PR review checklist.

---
*For deep-dives into specific modules (WebSockets, Mail, Search, etc.), refer to the [docs/](docs/) directory. For the bug-class catalog, see [INVARIANTS.md](./INVARIANTS.md).*
