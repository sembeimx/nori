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
*For deep-dives into specific modules (WebSockets, Mail, Search, etc.), refer to the [docs/](docs/) directory.*
