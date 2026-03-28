# Nori Developer Standards & AI Protocol

This document defines the coding standards, architectural patterns, and implementation protocols for the Nori framework. Developers and AI agents MUST adhere to these rules to ensure consistency, security, and maintainability.

---

## 1. Core Philosophy
1. **Keep it Native**: Use `core.*` modules. Avoid external libraries for Auth, JWT, Validation, Mail, Storage, or Tasks.
2. **Security by Default**: CSRF is mandatory, passwords are hashed with PBKDF2, and sensitive fields are protected in models.
3. **Convention over Configuration**: Follow the established directory structure and naming patterns without "magic" auto-discovery.

---

## 2. Naming & Coding Conventions
- **Controllers**: `PascalCase` with `Controller` suffix (e.g., `UserController`). Methods are `async snake_case`.
- **Models**: `PascalCase` (e.g., `User`). Tables are plural (e.g., `users`).
- **Routes**: Dot-notation for names (e.g., `articles.show`). Explicit `methods=` are mandatory.
- **Templates**: Grouped in folders matching the module name (e.g., `templates/auth/login.html`).
- **Type Hints**: Mandatory for all function signatures. Use `from __future__ import annotations`.

---

## 3. Implementation Workflow (The 7-Step Protocol)
When adding a new feature or module, follow these steps IN ORDER:

1. **Model**: Define fields in `models/name.py`. Inherit from `NoriModelMixin`.
2. **Register**: Import the model in `rootsystem/application/models/__init__.py`.
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
- `min:N`, `max:N`.
- `file`, `file_max:2mb`, `file_types:jpg,png`.

### Database Mixins
- **`NoriSoftDeletes`**: Use INSTEAD of `Model` for logical deletion (`deleted_at`).
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
