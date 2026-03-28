# Philosophy — What Nori is and what it isn't

## In one sentence

Nori is an **opinionated async web framework for Python** — structured, secure, and lightweight.

---

## Why Nori exists

Most Python web tools fall into two extremes: massive full-stack frameworks with steep learning curves, or minimal toolkits that leave every architectural decision to you.

Nori takes a different path: it makes decisions for you (project structure, auth, validation, controllers, CLI generators) while staying async-native and small enough to read end-to-end.

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

- **Not a monolith.** Nori includes what you need for most web projects, but it's not trying to be everything. It stays focused and auditable.
- **Not a microframework.** Nori has opinions about how your project should be structured. If you want total freedom to architect from scratch, use a lower-level toolkit.
- **Not an API-only framework.** Nori supports templates, flash messages, and server-rendered HTML alongside JSON APIs. It's for building full websites, not just REST endpoints.

---

## Target audience

Nori is for developers who:

- Want a structured, opinionated Python web framework
- Need async I/O without assembling dozens of packages
- Prefer a small, auditable codebase over a massive framework
- Are building server-rendered websites or hybrid apps (HTML + API)
