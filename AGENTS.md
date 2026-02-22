# Nori - AI Agent Instructions

This repository uses **Nori**, an asynchronous web boilerplate built on **Starlette** and **Tortoise ORM**. It is designed for fast, ergonomic development inspired by Laravel and Nori Engine.

## Project Philosophy & Rules
When modifying or extending this project, AI agents MUST follow these rules:

1. **Keep it Native**: The framework provides robust core features (`rootsystem/application/core/`). Use the built-in CSRF, JWT, validation, throttle, web sockets, email, file uploads, and collections. Avoid adding heavy external libraries.
2. **Class-based Controllers**: All business logic goes into class-based controllers in `rootsystem/application/modules/`.
3. **Explicit Routes**: Always define routes in `rootsystem/application/routes.py` with explicit `methods=` and `name=` for reverse routing.
4. **Security First**: 
   - State-changing actions (like `/logout` or `/delete`) MUST be `POST` requests to prevent CSRF via links.
   - Any response rendering a form that makes a POST request MUST include `csrf_field(request.session)` in the template context.
5. **Testing**: Fast E2E tests are located in `tests/` using in-memory SQLite and `httpx`. Unit tests for the core are in `tests/test_core/`. Ensure all new logic is tested.

## Core Features & Conventions

### 1. Database & Models (`rootsystem/application/models/`)
- Models inherit from `Tortoise.Model` and `NoriModelMixin` (which provides `.to_dict()`).
- Use `NoriSoftDeletes` for soft deletion (sets `deleted_at`) and `NoriTreeMixin` for hierarchical data.
- Register new models in `models/__init__.py` and configure them in `settings.TORTOISE_ORM`.

### 2. Validation (`core.http.validation`)
- Use declarative pipe-separated validation in controllers instead of manual checks.
- Example: `errors = validate(form, {'email': 'required|email|max:255', 'avatar': 'file|file_max:5mb|file_types:jpg,png'})`.

### 3. Collections (`core.collection`)
- Use `NoriCollection` (`collect()`) to handle lists of data or Tortoise query results. It provides methods like `where()`, `pluck()`, `map()`, and `chunk()`.

### 4. Authentication, JWT & Rate Limiting (`core.auth` & `core.http.throttle`)
- Use native decorators on controller methods: `@login_required`, `@require_role('admin')`, `@token_required` (for JWT APIs), and `@throttle('10/minute')`.
- Sessions are managed via `request.session`.
- Passwords should be hashed using `core.auth.security.Security`. Native JWT is supported via `core.auth.jwt`.
- Rate limiting (`@throttle`) supports pluggable backends (Memory or Redis) configured via the `THROTTLE_BACKEND` env var.

### 5. WebSockets (`core.ws`)
- Use `WebSocketHandler` or `JsonWebSocketHandler` by subclassing them for real-time endpoints.
- Define routes directly using `WebSocketRoute('/ws/...', Handler())` in `routes.py`.

### 6. Uploads & Email (`core.http.upload` & `core.mail`)
- Handle file saves securely using `save_upload()`, which checks extensions, MIME types, and sizes automatically.
- Send emails asynchronously with `send_mail()`, supporting Jinja2 templates via `aiosmtplib`.

### 7. Type Hints
- Use strict typing. Use `from __future__ import annotations` where necessary.

## Directory Structure
- `rootsystem/application/settings.py`: Configuration and environment variables.
- `rootsystem/application/routes.py`: Route definitions and Mounts.
- `rootsystem/application/modules/`: Application controllers.
- `rootsystem/application/models/`: Tortoise ORM models.
- `rootsystem/application/core/`: The Nori framework engine.
- `rootsystem/templates/`: Jinja2 templates.
- `tests/`: E2E tests and Core unit tests.

*Note: This file provides context to Claude, Gemini, ChatGPT, and any other AI agent interacting with this repository. It is symbolically linked as CLAUDE.md and GEMINI.md for convenience.*
