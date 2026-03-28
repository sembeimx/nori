# Philosophy — What Nori is and what it isn't

## In one sentence

Nori is an **opinionated async web framework for Python** — Laravel's ergonomics on top of Starlette's performance.

---

## The niche

There's a gap in the Python web ecosystem:

- **Django** is full-stack but synchronous-first, heavy, and opinionated in ways that fight async workloads.
- **FastAPI** is async and fast but unopinionated — it gives you Pydantic and OpenAPI, then leaves structure, auth, uploads, and everything else to you.
- **Flask/Quart** are minimal by design. You assemble everything yourself.

Nori sits where **AdonisJS sits in Node** or **Laravel sits in PHP**: a framework that makes decisions for you (project structure, auth, validation, controllers, CLI generators) while staying async-native and lightweight.

| | Django | FastAPI | Nori |
|---|--------|---------|------|
| Async-native | No (bolt-on) | Yes | Yes |
| Opinionated structure | Yes | No | Yes |
| Built-in auth + ACL | Yes | No | Yes |
| ORM included | Yes (own) | No | Yes (Tortoise) |
| CLI generators | No (manual) | No | Yes |
| Core size | ~250k LOC | ~15k LOC | ~3.4k LOC |

---

## Design principles

### 1. Keep it native
The **core framework** (`core/*`) should do as much as possible with pure Python. External dependencies are accepted only when reimplementing them would be irresponsible (cryptography, database drivers, SMTP). JWT, validation, file verification, collections, and pagination are all implemented in-house with zero extra dependencies.

**Optional service drivers** (`services/*`) may use external libraries (e.g., `httpx` for S3/Meilisearch). Drivers are application-level plug-ins — they are never imported by the core, never required to boot the framework, and can be removed without affecting any other feature.

**The test**: if removing a dependency breaks nothing except one feature, it's a good dependency. If removing it breaks the architecture, it shouldn't have been added.

### 2. Convention over configuration, but not magic
Controllers are classes. Routes are explicit. Validation is declarative. There's a right place for models, controllers, services, and templates. But there are no hidden model hooks, no implicit query scopes, no auto-importing. If something happens, you can trace it in the code.

### 3. Security by default, not by opt-in
CSRF is on. Security headers are on. Protected fields exclude sensitive data from serialization even if the developer forgets. Upload validation checks magic bytes, not just extensions. Rate limiting is a one-line decorator. The framework assumes the developer will forget — and covers for it.

### 4. Pluggable backends, stable interfaces
Cache, mail, storage, search, and rate limiting all follow the same pattern: a default backend that works out of the box, a registration function to add custom drivers, and a per-call override. The interface never changes; only the backend does.

### 5. Small core, big surface
The entire framework is ~3,400 lines. Every line is tested. Adding features is welcome; adding complexity is not. A feature earns its place by being used in most projects, not by being clever.

---

## What Nori is not

- **Not a Django replacement.** Django has a mature ORM, admin panel, ecosystem of packages, and 20 years of battle-testing. Nori doesn't compete with that. If you need Django's ecosystem, use Django.
- **Not a microframework.** Unlike Flask or Starlette raw, Nori has opinions about how your project should be structured. If you want freedom to architect from scratch, use Starlette directly.
- **Not an API-only framework.** Nori supports templates, flash messages, and server-rendered HTML alongside JSON APIs. It's for building full websites, not just REST endpoints.
- **Not production-complete yet.** The core is solid, but persistent job queues, OAuth, admin tooling, and i18n are still on the roadmap. See `roadmap.md` for the current state.

---

## Target audience

Nori is for developers who:

- Want Laravel/Adonis ergonomics in Python
- Need async I/O without assembling 15 packages
- Prefer a small, auditable codebase over a massive framework
- Are building server-rendered websites or hybrid apps (HTML + API), not pure SPAs with a separate backend

---

## Comparable frameworks

| Framework | Language | Relationship to Nori |
|-----------|----------|---------------------|
| **Laravel** | PHP | Primary inspiration — controller pattern, validation syntax, multi-driver services, CLI generators, soft deletes |
| **AdonisJS** | Node | Closest sibling — opinionated, async-native, Laravel-inspired, similar maturity stage |
| **Litestar** | Python | Similar ambition (async, class-based, opinionated) but heavier on type system and OpenAPI |
| **Sanic** | Python | Async Python peer, more batteries-included but less structured |
| **FastAPI** | Python | Same foundation (Starlette) but opposite philosophy — FastAPI is unopinionated, Nori is opinionated |
