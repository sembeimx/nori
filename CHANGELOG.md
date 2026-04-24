# Changelog

All notable changes to Nori are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/).

---

## [1.7.0] — 2026-04-24

### Added
- **Split requirements**: framework deps now live in their own `requirements.nori.txt` at the project root, and the site's `requirements.txt` inlines them via `-r requirements.nori.txt`. The new file is framework-owned (replaced on every `framework:update`, backed up under `rootsystem/.framework_backups/`), while `requirements.txt` remains user-owned — only patched once to add the `-r` line. This eliminates silent drift of framework minimums on upgrade.
- **`_FRAMEWORK_FILES` update support**: `framework:update` now handles individual files (not just directories). Extracts, backs up, and replaces any entry registered in `_FRAMEWORK_FILES` with the same semantics as `_FRAMEWORK_DIRS`.
- **Reload-safe patch system** (`core/_patches.py`): moved `_patch_bootstrap_hook_in_asgi` and the dispatcher `apply()` out of `core/cli.py` into a dedicated module. `framework_update()` clears it from `sys.modules` and re-imports it after the framework replace, so patches added in a release can actually fire on the same update that ships them — closing the first-update trap that hit 1.6.0.
- **New patcher `_patch_requirements_dash_r_to_nori`**: idempotently prepends `-r requirements.nori.txt` to an existing `requirements.txt` on upgrade, preserving any user deps and comments.
- **Dependencies docs** (`docs/dependencies.md`): rationale for the split, how to add site deps, activating optional drivers, stricter pins, upgrade path, dev deps.
- 7 new tests for the requirements patcher (idempotency, leading comments, missing file, full `apply()` runs) and for the patcher error-isolation path. Suite: 551 → 558 total.

### Changed
- `core/cli.py` no longer contains patch logic. `framework_update()` imports `core._patches` via `importlib` after clearing `sys.modules`, so the freshly-installed bytecode runs.
- `requirements.txt` in the framework repo is now the scaffold template: starts with `-r requirements.nori.txt`, optional drivers commented, placeholder section for site deps.

### Upgrade note
- **Coming from ≤ 1.6**: the first `framework:update` to 1.7.0 still requires the two-step run (`framework:update` then `framework:update --force`) because the old `cli.py` in memory does not know about the reload trick. After that, patches apply automatically on every update — the trap is closed from 1.7 onwards.
- Your existing `requirements.txt` is preserved. After the patch, it will start with `-r requirements.nori.txt` and your old deps remain below. pip deduplicates entries that also appear in `requirements.nori.txt`; stricter pins in your file still win. You may optionally remove the framework entries from your file to keep it clean.

---

## [1.6.0] — 2026-04-24

### Added
- **Bootstrap hook** (`core/bootstrap.py`): optional `rootsystem/application/bootstrap.py` with a top-level `bootstrap()` function runs as the very first thing in the ASGI entry point, before Starlette, Tortoise, or any other third-party import. This is the correct moment to initialise observability SDKs (Sentry, Datadog, OpenTelemetry) that patch libraries at import time. The hook is optional — if the file is absent, `load_bootstrap()` is a no-op; if it imports or raises, a warning is logged on `nori.bootstrap` and the app still starts.
- **`framework:update` patch system**: after replacing the framework directories, the update command now applies idempotent patches to user-land files so new core features that need a hook in `asgi.py` are wired up automatically. First patch: injects the bootstrap hook call into `asgi.py` after the `from __future__` import and module docstring, preserving any user customizations. A timestamped backup is kept in `rootsystem/.framework_backups/`.
- **Observability docs** (`docs/observability.md`): rationale for the hook design, the Sentry recipe end-to-end, notes on Datadog (`ddtrace-run`) and OpenTelemetry, and the upgrade path for sites on Nori ≤ 1.5.
- 16 new tests for the bootstrap loader (file absent, function present, idempotency, missing function, raising hook, import error, syntax error) and the asgi.py patcher (injection positions, idempotency, missing file, syntax error, AST validity of the patched output). Suite: 535 → 551 total.

### Upgrade note
- **First-time upgrade to 1.6.0 requires two steps** (`framework:update` then `framework:update --force`). The running Python process has the OLD `cli.py` in memory, so the patcher shipped in 1.6.0 does not fire on the same run that installs 1.6.0. The `--force` re-run executes under the new `cli.py` and applies the patch. This is a one-time quirk — from 1.6.x onwards patches run automatically. See [docs/observability.md](https://nori.sembei.mx/observability/#upgrading-an-existing-site).

---

## [1.5.0] — 2026-04-21

### Added
- **Google Cloud Storage driver** (`services/storage_gcs.py`): native GCS storage backend using service account JWT → OAuth2 access token exchange (no `google-cloud-storage` SDK). Signs RS256 JWTs with the service account's private key, caches the 1-hour Bearer token in-process with async-safe refresh 60 s before expiry, and uploads via the GCS XML API (`PUT https://storage.googleapis.com/{bucket}/{key}`). Supports loading credentials from a file (`GCS_CREDENTIALS_FILE`) or an inline JSON string (`GCS_CREDENTIALS_JSON`) for containerised deployments. Optional `GCS_URL_PREFIX` for CDN-fronted public URLs.
- 16 new tests for the GCS driver covering JWT construction and signature verification with a real throwaway RSA keypair, token caching and refresh logic, credentials loading precedence, and upload URL construction. Suite: 519 → 535 total.

### Changed
- `requirements.txt` lists `cryptography>=42.0` as an optional dep (commented) — only required when enabling the GCS driver. Dev dependency pinned in `requirements-dev.txt` so CI runs the new tests.

---

## [1.4.0] — 2026-04-10

### Added
- **Async validation** (`validate_async`): superset of `validate()` that supports database-dependent rules. Runs sync rules first, then async rules only for fields that passed.
- **`unique` validation rule**: checks value uniqueness against the database. Syntax: `unique:table,column` or `unique:table,column,except_id` for updates. SQL injection protected via identifier validation.
- **`routes:list` CLI command**: prints a table of all registered routes with path, methods, and name. Supports `Route`, `Mount` (recursive), and `WebSocketRoute`.
- **Middleware documentation** (`docs/middleware.md`): full middleware stack reference, parameter docs for all built-in middleware, custom middleware guide with ASGI patterns.
- 11 new tests (508 → 519 total).

---

## [1.3.1] — 2026-04-10

### Added
- **Testing utilities** (`core.testing`): `create_test_client()`, `setup_test_db()` / `teardown_test_db()`, `authenticate()` with signed session cookies, `authenticate_api()`, `ModelFactory` base class, `assert_redirects()` / `assert_json_error()`, `clear_authentication()`.
- 90 new tests: validation rules (34), Redis queue (8), CLI plugins (11), testing module (26), mail_resend service (4), storage_s3 service (7). Suite: 418 → 508 total.
- GitHub Actions CI running on Python 3.9, 3.12, and 3.14.

### Fixed
- `asyncio.iscoroutinefunction` replaced with `inspect.iscoroutinefunction` (deprecated Python 3.14, removed 3.16).
- `authenticate()` now creates real signed session cookies compatible with `@login_required` and `@require_role` (previously used non-functional `X-Test-*` headers).
- Session cookie cleared before re-authenticating to avoid duplicates across httpx versions.
- `datetime.utcnow()` replaced with `tortoise.timezone.now()` in getting_started tutorial seeder.
- `index.md`: removed hardcoded line count, added venv/.env to Quick Start, added missing features to Key Features section.
- `.env.example`: added `QUEUE_DRIVER`, `CACHE_MAX_KEYS`, `TRUSTED_PROXIES`, consolidated `REDIS_URL`.

---

## [1.3.0] — 2026-04-10

### Added
- **Redis queue driver**: `QUEUE_DRIVER=redis` enables near-instant job pickup via BRPOP, delayed jobs via sorted sets, and a dead letter list at `nori:queue:{name}:failed`. The worker auto-dispatches to database or Redis based on config.
- **CLI plugin system**: Custom commands now live in `commands/*.py` and survive `framework:update`. Each file exports `register(subparsers)` and `handle(args)`. Files prefixed with `_` are skipped. Example provided at `commands/_example.py`.
- **8 new validation rules**: `url`, `date` (ISO 8601), `confirmed` (field_confirmation pattern), `nullable` (skip all rules if empty), `array`, `min_value:N` / `max_value:N` (numeric range), `regex:pattern`.
- **Testing utilities** (`core.testing`): `create_test_client()`, `setup_test_db()` / `teardown_test_db()`, `authenticate()` / `authenticate_api()`, `ModelFactory` base class, `assert_redirects()` / `assert_json_error()` assertion helpers.
- 76 new tests covering all new features (418 → 494 total).

### Fixed
- `file_max` validation rule no longer crashes the server on invalid size values — `ValueError` from `_parse_size` is caught and returned as a validation error.

---

## [1.2.5] — 2026-04-10

### Fixed
- Documentation: corrected `@inject()` resolution order, removed non-existent Redis queue driver reference, fixed WebSocket `on_receive` → `on_receive_json` example, fixed `Content-Type` → `Accept` header reference in auth decorators.
- Documentation: fixed logging text format example to match actual formatter output.
- `docker-compose.yml` now includes `MYSQL_USER` and `MYSQL_PASSWORD` for the db service.

### Changed
- All 5 service drivers (`mail_resend`, `storage_s3`, `oauth_github`, `oauth_google`, `search_meilisearch`) now use `core.conf.config` instead of `import settings` directly, consistent with the core decoupling convention.
- Test dependencies (`pytest`, `pytest-asyncio`) moved to `requirements-dev.txt`. Production installs no longer include test tooling.

### Added
- Documentation for previously undocumented features: `run_in_background()`, `background_tasks()`, rate-limit response headers (`X-RateLimit-*`), `validate()` custom messages parameter, `framework:update --force` flag, `tree(root_id=)` subtree parameter, HSTS `includeSubDomains` directive and `hsts`/`csp` constructor params, 5 missing framework loggers.
- Warning in CLI docs about `framework:update` overwriting custom commands in `core/cli.py`.

---

## [1.2.4] — 2026-04-08

### Fixed
- `migrate:fresh` now re-creates the empty database after dropping it, fixing a failure on MySQL/Postgres where `aerich init-db` would error because the database no longer existed.

---

## [1.2.3] — 2026-04-08

### Added
- `migrate:fix` command to synchronize Aerich migration files with the current model state.
- `migrate:fresh` command (robust version) to wipe the database, delete application migrations, and re-initialize the system. Includes safety checks for `DEBUG=true` and user confirmation.

---

## [1.2.2] — 2026-04-06

### Fixed
- Memory queue driver now executes jobs via `asyncio.create_task()` — previously created a `BackgroundTask` that was never attached to a Response, so enqueued jobs silently never ran.

### Changed
- CLI logic moved from `nori.py` to `core/cli.py`. The entry point is now a thin bootstrap that delegates to core, so the CLI self-updates with `framework:update`.
- Repository migrated from GitLab to GitHub. All URLs, API calls, and documentation updated accordingly.
- `framework:update` now uses the GitHub Releases API.

### Note
Projects on v1.2.1 or earlier need to manually replace `nori.py` once with the new bootstrap version. After that, all future updates are automatic.

---

## [1.2.1] — 2026-03-28

### Added
- `audit:purge` command for cleaning audit log entries older than N days, with `--export` (CSV) and `--dry-run` options.
- `--force` flag for `framework:update` to re-install even when already on the target version.
- Database indexes on `AuditLog` for `user_id`, `action`, `model_name`, and `created_at`.

### Fixed
- Backup path collision in `framework:update` when running multiple updates on the same version.
- Regenerated framework init migration with correct Aerich `MODELS_STATE`.

---

[1.4.0]: https://github.com/sembeimx/nori/releases/tag/v1.4.0
[1.3.1]: https://github.com/sembeimx/nori/releases/tag/v1.3.1
[1.3.0]: https://github.com/sembeimx/nori/releases/tag/v1.3.0
[1.2.5]: https://github.com/sembeimx/nori/releases/tag/v1.2.5
[1.2.4]: https://github.com/sembeimx/nori/releases/tag/v1.2.4
[1.2.3]: https://github.com/sembeimx/nori/releases/tag/v1.2.3
[1.2.2]: https://github.com/sembeimx/nori/releases/tag/v1.2.2
[1.2.1]: https://github.com/sembeimx/nori/releases/tag/v1.2.1
