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
6. **Templates**: Create Jinja2 views. Use `{{ csrf_field(request.session)|safe }}` for POST forms.
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
- **`push(func_path, *args)`**: Persistent, queued task (requires `python3 nori.py queue:work`).

---

## 6. Security Mandates
- **POST only**: All state-changing actions (Logout, Delete, Update) MUST be `POST`.
- **Audit Logging**: Use `audit(request, action, model_name, record_id)` for sensitive operations.
- **Serialization**: Always use `.to_dict()` to leverage `protected_fields` safety.

---

## 7. Operational Pitfalls (for framework changes)

These are Nori-specific traps discovered the hard way. Read before changing the listed areas.

### Hosting and docs deploys
- `nori.sembei.mx` runs on **Firebase Hosting**, not a VPS. Deploy is automatic via `.github/workflows/deploy-docs.yml` on every push to `main` that touches `docs/**` or `mkdocs.yml`. No manual `firebase deploy` is needed.
- The version badge in the docs sidebar is **client-side JavaScript** — the GitHub repo widget queries the API at page load. When it looks stale after a release, the fix is browser cache (hard reload, or unregister the service worker). Re-running the deploy workflow will NOT update it.
- Verify the actual host with `dig +short nori.sembei.mx` before assuming. Memory of past deploys can be stale.

### Releases and the installer
- `gh release create` → `releases/latest` API has a ~30-second indexing lag. The installer (`docs/install.py`) hits `releases/latest` by default, so the first install within ~1 minute of a release may pull the previous version. For testing right after release, pass `--version VX.Y.Z` to skip the latest endpoint.
- Always verify a release end-to-end with the installer (real `curl ... | python3 -`) before considering it shipped.

### CLI subprocess scripts (`core/cli.py`)
- When a CLI command spawns a Python subprocess that imports user code (`routes`, `modules`, `models`), the script MUST start with:
  ```python
  import sys
  sys.path.insert(0, '.')
  import settings
  from core.conf import configure
  configure(settings)
  ```
  before importing anything that may touch `config.X`, `templates.env`, or any lazy framework state. Otherwise the command crashes with `RuntimeError: Nori config not initialised` on projects whose user code touches config at module-import time. See `migrate_init`, `migrate_upgrade`, `routes_list` for the established pattern.
- For aerich subprocesses, use `env=_quiet_env()` to suppress the `Module "X" has no models` RuntimeWarning. The same warning is filtered in-process via `core/__init__.py`.

### Path resolution must be CWD-independent
- `nori.py` adds `rootsystem/application` to `sys.path` but does NOT `chdir` into it. Code that resolves files/modules must NOT use `pathlib.Path('something')` (CWD-relative). Anchor to the module file:
  ```python
  pathlib.Path(__file__).resolve().parent.parent / 'something'
  ```
- When a function changes its path resolution or discovery contract, grep ALL test files for fixtures using `monkeypatch.chdir` or `monkeypatch.setattr` against the affected module BEFORE shipping. CI catches this but a 30-second grep avoids the red CI + follow-up commit.

### Repo-state lints catch ship-time bugs that unit tests miss
- Some bugs are not in code but in committed files (the v1.8.0 → v1.10.2 incident: leftover `.gitkeep` files that silently broke `migrate:init` for two releases). Unit tests of the affected function passed because the test environment didn't have the bad files. The right test layer is a static repo-state assertion. See `test_repo_does_not_ship_migrations_dir` for the pattern.
- When fixing "the repo shouldn't ship X" bugs, add a regression test that asserts the file/dir doesn't exist in the source tree.

### Configurable URLs / settings have defaults via `config.get(key, default)`
- New user-overridable settings (like `LOGIN_URL`, `FORBIDDEN_URL`, `PERMISSIONS_TTL`) use `config.get('SETTING', default_value)` rather than `config.SETTING`. This keeps existing projects working when they haven't set the new key, while letting projects override via `settings.py`. Always provide a default that matches the previous hardcoded behavior — backward compatibility is non-negotiable.

---
*For deep-dives into specific modules (WebSockets, Mail, Search, etc.), refer to the [docs/](docs/) directory.*
