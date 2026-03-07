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

### 2. Validation & Dependency Injection (`core.http.validation` & `core.http.inject`)
- Use declarative pipe-separated validation in controllers instead of manual checks.
- Example: `errors = validate(form, {'email': 'required|email|max:255', 'avatar': 'file|file_max:5mb|file_types:jpg,png'})`.
- Use `@inject()` decorator on controller methods to automatically map `request.form()`, `request.query_params`, and `request.path_params` into type-hinted arguments instead of extracting them manually.

### 3. Collections (`core.collection`)
- Use `NoriCollection` (`collect()`) to handle lists of data or Tortoise query results. It provides methods like `where()`, `pluck()`, `map()`, and `chunk()`.

### 4. Authentication, JWT, ACL & Rate Limiting (`core.auth` & `core.http.throttle`)
- Use native decorators on controller methods: `@login_required`, `@require_role('admin')`, `@require_permission('articles.edit')`, `@token_required` (for JWT APIs), and `@throttle('10/minute')`.
- For granular permissions, use `@require_permission('resource.action')`. At login time, call `await load_permissions(request.session, user.id)` to cache the user's permissions from the `Role→Permission` M2M into the session. Admin role bypasses all permission checks.
- `Permission` model: name (dot-notation, e.g. `articles.edit`) + description. `Role` model: name + M2M to Permission via `role_permission` table.
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

### 8. Background Tasks (`core.tasks`)
- Use `background(func, *args, **kwargs)` to create a `BackgroundTask` that logs errors instead of crashing.
- Use `run_in_background(response, func, *args, **kwargs)` to attach a background task to an existing response.
- Supports both sync and async callables.

### 9. Caching (`core.cache`)
- Pluggable backends: `MemoryCacheBackend` (default) and `RedisCacheBackend`, configured via `CACHE_BACKEND` env var.
- Convenience functions: `cache_get(key)`, `cache_set(key, value, ttl)`, `cache_delete(key)`, `cache_flush()`.
- Use `@cache_response(ttl=60)` decorator to cache GET responses automatically.

### 10. Request ID Tracing (`core.http.request_id`)
- `RequestIdMiddleware` generates a UUID per HTTP request and sets `X-Request-ID` response header.
- Accessible as `request.state.request_id`. Supports propagation from incoming `X-Request-ID` header.

### 11. Audit Logging (`core.audit`)
- Use `audit(request, 'create', model_name='Article', record_id=article.id)` to create an audit log entry as a background task.
- Returns a `BackgroundTask` — pass it to the response: `return JSONResponse({...}, background=task)`.
- Automatically captures `user_id` from session, client IP (with `X-Forwarded-For` support), and `request_id` from middleware.
- `AuditLog` model stores: user_id, action, model_name, record_id, changes (JSON), ip_address, request_id, created_at.
- Also emits structured log via `get_logger('audit')`.
- `get_client_ip(request)` extracts the real client IP, respecting reverse proxies.

### 12. Database Seeding (`seeders/`)
- Each seeder module defines an `async def run()` function.
- Register seeders in `seeders/database_seeder.py` SEEDERS list.
- Run with `python3 nori.py db:seed`.

### 13. Nori CLI (`nori.py`)
- `python3 nori.py serve` — Start the dev server with hot reloading.
- `python3 nori.py make:controller Name` / `make:model Name` / `make:seeder Name` — Generate boilerplate.
- `python3 nori.py migrate:init` / `migrate:make <name>` / `migrate:upgrade` / `migrate:downgrade` — Aerich database migrations.
- `python3 nori.py db:seed` — Run database seeders.

## How to Create a New Module (AI Agent Workflow)
When asked by the user to "create a new feature", "add a module", or "add a table", you MUST strictly follow this sequence:

1. **Generate the Model**: Run `python3 nori.py make:model Category`. 
2. **Define Schema**: Edit the generated file in `rootsystem/application/models/category.py` to add Tortoise fields (`fields.CharField`, `fields.IntField`, etc).
3. **Register the Model**: Open `rootsystem/application/models/__init__.py` and add the import (e.g., `from models.category import Category`), otherwise Tortoise will fail to create the table.
4. **Generate the Controller**: Run `python3 nori.py make:controller Category`.
5. **Implement Logic**: Edit the generated file in `rootsystem/application/modules/category.py`. Use the `@inject()` decorator to automatically map `.form()`, request inputs, or parameters into your async methods. Return `JSONResponse(...)` or `templates.TemplateResponse(request, 'template.html', context)`.
6. **Map Routes**: Open `rootsystem/application/routes.py`. Import your controller, instantiate it globally (e.g., `category = CategoryController()`), and add its Routes to the `routes` list using a `Mount` or individual `Route` objects. Always provide a `name=`.
7. **Create Views**: If returning HTML, create the corresponding jinja templates under `rootsystem/templates/category/`.

## Directory Structure
- `rootsystem/application/settings.py`: Configuration and environment variables.
- `rootsystem/application/routes.py`: Route definitions and Mounts.
- `rootsystem/application/modules/`: Application controllers.
- `rootsystem/application/models/`: Tortoise ORM models.
- `rootsystem/application/seeders/`: Database seeders.
- `rootsystem/application/core/`: The Nori framework engine.
- `rootsystem/templates/`: Jinja2 templates.
- `tests/`: E2E tests and Core unit tests.
- `tests/factories.py`: Test factories (`make_article`, `make_post`, `make_category`).

*Note: This file provides context to Claude, Gemini, ChatGPT, and any other AI agent interacting with this repository. It is symbolically linked as CLAUDE.md and GEMINI.md for convenience.*
