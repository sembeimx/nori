# Changelog

All notable changes to Nori are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/).

---

## [1.10.8] — 2026-04-26

### Added

- **Test coverage tracking with `pytest-cov`.** Every test run now measures branch coverage of `rootsystem/application` and reports a per-file table at the end. The `Tests` workflow fails any push or PR that drops below the configured floor.

  Configuration in `pyproject.toml` under `[tool.coverage]`:
  - `source = ["rootsystem/application"]` — framework code only
  - `branch = true` — both lines AND conditional branches must be covered
  - `fail_under = 75` — floor (intentionally below today's baseline so refactors have room; raise as the project sustains higher numbers)
  - Excludes `migrations/`, `seeders/example_seeder.py`, and `commands/_example.py` (templates meant to be edited by users)

  `pytest-cov>=5.0` added to `requirements-dev.txt`. Existing projects can opt in by copying the `[tool.coverage]` sections to their own `pyproject.toml`.

- **Pre-commit hooks for ruff lint + format.** New `.pre-commit-config.yaml` at repo root pinned to `astral-sh/ruff-pre-commit` v0.15.12. Runs `ruff check --fix` and `ruff format` on every `git commit` so violations are caught locally instead of waiting for CI.

  Activation per clone:
  ```bash
  .venv/bin/pip install -r requirements-dev.txt
  .venv/bin/pre-commit install
  ```

  `pre-commit>=3.5` added to `requirements-dev.txt`. The `.pre-commit-config.yaml` ships to fresh projects via the starter manifest.

- **Security rules (`S`) enabled in ruff.** flake8-bandit checks for hardcoded secrets, SQL injection patterns, weak hashes, insecure subprocess calls, `/tmp` paths, and similar issues. The rule set ran clean against the current codebase: 975 raw findings triaged to 0 violations, zero real security bugs found.

  Most findings were structural false positives (`assert` is the language of pytest, framework subprocess calls use hardcoded args, `_TOKEN_URL` constants are public OAuth endpoints not secrets, recursive CTE queries already validate identifiers via `_IDENTIFIER_RE` / `isalnum()`). Each per-file-ignore in `pyproject.toml` carries a justification comment naming the architectural reason — no silent suppressions.

### Docs

- `docs/code_quality.md` — added "Pre-commit hooks" and "Test coverage" sections covering activation, manual all-files runs, version bumps, threshold tuning, exclusion list, and adoption steps for existing projects.

### Compatibility

- No API changes. Existing projects are unaffected — `framework:update` does not touch user-owned `requirements-dev.txt`, `pyproject.toml`, or repo-root configuration files. To adopt any of the three additions in an existing project, follow the relevant section of the new Code Quality docs:
  - Add `pytest-cov>=5.0` to `requirements-dev.txt` and copy the `[tool.coverage]` sections
  - Add `pre-commit>=3.5` to `requirements-dev.txt`, copy `.pre-commit-config.yaml`, and run `pre-commit install`
  - Add `S` to your ruff `select` and define your own per-file-ignores for tests and any framework-internal subprocess wrappers

---

## [1.10.7] — 2026-04-26

### Fixed
- **Module docstrings restored on 17 framework files.** Placing `from __future__ import annotations` BEFORE the module docstring is syntactically valid Python but breaks docstring detection — Python only treats a string literal as the module docstring when it is the FIRST expression in the module. With the future import first, `module.__doc__` was `None`, making the docstring invisible to `help()`, `pydoc`, IDE tooltips, and doc-gen tools. Fixed by moving the future import after the docstring on:
  - `core/conf.py`, `core/logger.py`, `core/mail.py`, `core/registry.py`
  - `core/auth/oauth.py`, `core/http/security_headers.py`
  - `services/{mail_resend,oauth_github,oauth_google,search_meilisearch,storage_gcs,storage_s3}.py`
  - `modules/echo.py`, `modules/health.py`
  - `asgi.py`, `seeders/database_seeder.py`, `seeders/example_seeder.py`

  Most notable: `asgi.py.__doc__` was `None` despite the file being explicitly singled out in `AGENTS.md` for its bootstrap pattern. The docstring documenting the uvicorn invocation was invisible to all tooling.

- **Silent test in `tests/test_core/test_settings_validation.py`.** The test `test_validate_settings_warns_missing_db_user` was named "warns" but its setup used `DEBUG=True`, where DB credential warnings are intentionally skipped per the validation logic. It called `validate_settings()`, assigned the result to a `warnings` local, and never asserted anything. Renamed to `test_validate_settings_skips_db_check_in_debug`, removed a dead `pass`-only `with` block, and added the assert that the inline comment implied. Would catch any regression in the DEBUG-skip behavior.

- **Minor exception/comparison cleanup in `core/http/`.**
  - `validation.py`: 4 `raise ValueError(...)` inside `except` clauses now use `from None` to suppress the noisy `int()`/`float()` chain. The framework's message ("Invalid parameter for 'min' rule: 'abc'") is self-contained; the suppressed chain keeps developer-facing tracebacks clean.
  - `inject.py`: 2 `param.annotation == dict` checks changed to `param.annotation is dict`. Semantically equivalent for class-object checks, more idiomatic, and avoids any custom `__eq__` weirdness on type objects.

- **`tests/test_core/test_queue_redis.py::test_redis_worker_processes_job` order dependency.** Pre-existing test that failed when run in isolation but passed in the full suite. Root cause: the test serializes a job referencing `tests.test_core.test_queue_redis:_dummy_task` and the queue worker calls `importlib.import_module('tests.test_core.test_queue_redis')`. The `tests/conftest.py` inserted `tests/` and `rootsystem/application/` on `sys.path` but not the project root — so the `tests` package itself wasn't importable. Fixed by also inserting the project root in conftest.py. Other tests that need the same dotted-path resolution now work consistently regardless of run order.

### Added
- **Ruff configured framework-wide.** New `pyproject.toml` at the repo root with a conservative lint selection (`E, W, F, I, UP, B`) and `quote-style = "single"` matching the existing 3000+ string-literal convention in the codebase. `ruff>=0.6` added to `requirements-dev.txt`. The `pyproject.toml` ships to fresh projects via the starter manifest, so new Nori projects come pre-configured with the same lint/format setup. Per-file-ignores document the legitimate `E402` cases (`asgi.py` bootstrap, `core/__init__.py` filterwarnings, `settings.py` load_dotenv, `tests/**/*.py` setup patterns) — see comments in `pyproject.toml`.

  **Existing projects are unaffected** — `framework:update` does not touch user-owned `requirements-dev.txt` or repo-root config files. To adopt: add `ruff>=0.6` to your `requirements-dev.txt`, copy `pyproject.toml` from the framework repo, and run `.venv/bin/pip install -r requirements-dev.txt`.

### Changed
- **Codebase passed through `ruff check --fix`** — 153 mechanical fixes across 76 files: isort import ordering, removed unused imports (excluding `__init__.py` re-exports), trimmed trailing whitespace on blank lines, dropped empty f-string prefixes (`f""` → `""`), minor pyupgrade modernizations. No behavioral changes.

---

## [1.10.6] — 2026-04-26

### Fixed
- **Auth decorators no longer hardcode `/login` and `/forbidden`.** Pre-1.10.6, `login_required`, `require_role`, `require_any_role`, and `require_permission` all redirected unauthenticated/unauthorized requests to literal `/login` and `/forbidden` URLs (7 hardcoded strings across `core/auth/decorators.py`). Projects mounting auth elsewhere — admin panels at `/admin/login`, custom `/access-denied` flows — had to ship shim routes. Now configurable via two new settings:

  ```python
  # settings.py
  LOGIN_URL = '/admin/login'        # default: '/login'
  FORBIDDEN_URL = '/access-denied'  # default: '/forbidden'
  ```

  Backward-compatible: projects without these settings keep the original `/login` and `/forbidden` behavior. `@token_required` is unaffected (always returns JSON 401, no redirect path).

- **`_load_user_commands` now resolves `commands/` relative to the cli module file, not CWD.** Latent bug from the v1.3.0 plugin system release. `nori.py` adds `rootsystem/application` to `sys.path` but does NOT chdir into it, so `pathlib.Path('commands')` resolved against the user's CWD (typically the project root) and silently missed the real `commands/` dir at `rootsystem/application/commands/`. Custom commands never loaded; the workaround was to invoke `nori.py` from inside `rootsystem/application/`. Fixed by anchoring to `pathlib.Path(__file__).resolve().parent.parent / 'commands'`.

### Added
- **Regression tests**:
  - `test_login_required_uses_login_url_setting` and `test_require_role_forbidden_uses_forbidden_url_setting` — assert that overriding the new settings changes the redirect target.
  - `test_load_user_commands_resolves_relative_to_module_not_cwd` — sets up a fake project layout in `tmp_path`, monkeypatches `cli.__file__`, moves CWD elsewhere, asserts the user command is still discovered.

### Docs
- `docs/authentication.md` — added a "Customizing the redirect URLs" subsection under the decorators reference, showing how to set `LOGIN_URL` / `FORBIDDEN_URL` in `settings.py` and noting which decorators they apply to.

---

## [1.10.5] — 2026-04-26

### Fixed
- **`routes:list` now boots Nori config before importing routes.** Latent bug since v1.4.0 when the command was added: the subprocess script ran `from routes import routes` without first calling `core.conf.configure(settings)`. Fresh framework code didn't access `config` at module-import time anywhere in the routes import chain, so the bug stayed invisible. But any user module imported transitively by `routes.py` that touched `templates.env`, jinja filters, or `config.X` at import time crashed the command with `RuntimeError: Nori config not initialised`. Fixed by adding the standard `import settings; configure(settings)` prelude that other subprocess scripts (`audit:purge`, `db:seed`, `migrate:fresh`) already use.
- **`routes:list` count line**: the trailing `print(f'  {len(rows)} route(s) registered.')` was over-escaped (`{{len(rows)}}`) in the dedented script, so it printed the literal text `{len(rows)} route(s) registered.` instead of the actual count. Cosmetic but visible on every invocation.

### Added
- **Regression test** `test_routes_list_configures_settings_before_importing_routes` asserts the subprocess script contains `configure(settings)` AND that it appears before `from routes import` in the script text. Catches re-introduction of the same bug at CI time.

---

## [1.10.4] — 2026-04-26

### Changed
- **`migrate:init` and `migrate:upgrade` now discover apps dynamically** from `settings.TORTOISE_ORM['apps']` instead of hardcoding `('framework', 'models')`. Users who wire a third app (e.g. an `analytics` schema with its own models) get it initialized and upgraded along with the standard pair, with no extra CLI flags. Existing two-app projects behave identically. Falls back to `('framework', 'models')` if `settings.py` can't be loaded for any reason.
- **`migrate:fresh` now wipes ALL migration files** (framework + models + extras), then delegates to `migrate:init` to regenerate everything against the current DB engine. Previously preserved `migrations/framework/` — that was correct pre-1.8.0 when framework migrations shipped pre-generated, but post-1.8.0 framework migrations are user-owned and engine-specific. Their content is derived from the same framework model definitions on every machine, so regenerating is lossless. Keeps "fresh" honest to its name.

### Added
- **Repo-state lint test** (`test_repo_does_not_ship_migrations_dir`): asserts the framework repo never commits `rootsystem/application/migrations/`. The leftover `.gitkeep` files that caused the 1.8.0 → 1.10.2 silent breakage of `migrate:init` would have been caught at commit time by this test. CI fails immediately if anyone re-introduces a `migrations/` dir to the repo.
- **Dynamic-apps test** (`test_migrate_init_uses_dynamic_apps_from_tortoise_orm`, `test_migrate_upgrade_without_app_uses_dynamic_app_list`): assert that custom apps declared in `settings.TORTOISE_ORM` flow through `migrate:init` and `migrate:upgrade`.

---

## [1.10.3] — 2026-04-26

### Fixed
- **`migrate:init` now actually generates migration files on fresh projects.** Removed leftover `.gitkeep` files in `rootsystem/application/migrations/framework/` and `rootsystem/application/migrations/models/`. They were committed pre-1.8.0 (back when `migrations/framework/` shipped a pre-generated SQLite-only migration) and never removed when 1.8.0 made framework migrations user-owned. The empty-but-present directories tricked aerich's `init-db` idempotent check — it concluded "already initialized" and bailed without creating the initial migration files. Tortoise's `generate_schemas()` in the asgi lifespan was silently masking the bug by creating tables on first serve, but the missing migration baseline broke the user's first `migrate:make` later in the dev cycle.

  After this fix: `migrate:init` on a fresh project generates `migrations/framework/0_<ts>_init.py` and `migrations/models/0_<ts>_init.py` against the project's actual DB engine. Subsequent `migrate:make` commands diff against these baselines correctly.

  **Existing projects are unaffected** — their `migrations/` directories already contain real migration files and aerich's idempotent check works as intended on them.

---

## [1.10.2] — 2026-04-26

### Fixed
- **Silenced Tortoise's `RuntimeWarning: Module "X" has no models`** during `serve`, `shell`, tests, and all `migrate:*` commands. The warning is fired by Tortoise whenever a configured app has no `Model` subclasses — which is normal-by-design in Nori for fresh projects (the user's `models` app starts empty) and for apps that only consume framework models. The warning isn't actionable: real registration bugs surface as failed queries or missing tables, not as this warning. Clean boot output.
  - In-process suppression: `core/__init__.py` registers a `warnings.filterwarnings()` for the specific `Module ".+" has no models` message (RuntimeWarning category).
  - Subprocess suppression: `core/cli.py` adds a `_quiet_env()` helper that injects `PYTHONWARNINGS=ignore::RuntimeWarning` into every `aerich` subprocess call (`migrate:init`, `migrate:make`, `migrate:upgrade`, `migrate:downgrade`, `migrate:fresh`, `migrate:fix`).

---

## [1.10.1] — 2026-04-26

### Changed
- **`.env.example` defaults to SQLite** instead of MySQL. Fresh projects now boot with no external services required — `migrate:init` and `serve` work out of the box on any machine that has Python. MySQL/PostgreSQL connection settings remain in `.env.example` (commented as alternates) for users who switch later. Aligns Nori with Django/Rails/Laravel, which all default to SQLite for first run. Only affects new projects (existing projects have their own `.env` and are unaffected).

### Docs
- `docs/installation.md` notes the SQLite default and points to `docs/deployment.md` for switching to MySQL/PostgreSQL.

---

## [1.10.0] — 2026-04-26

### Added
- **`install.py` installer.** Creates clean Nori projects without inheriting framework dev artifacts (`CHANGELOG.md`, `CONTRIBUTING.md`, `AGENTS.md`, `docs/`, `mkdocs.yml`, `.github/`, the framework's own `tests/`, etc.). Pulls the latest release zip from GitHub, extracts only the paths listed in `.starter-manifest.json`, writes a project-scoped `README.md`, copies `.env.example` to `rootsystem/application/.env`, and runs `git init` so the user's first commit is theirs (not Nori's history). Hosted at `nori.sembei.mx/install.py`.
  - Usage: `curl -fsSL https://nori.sembei.mx/install.py | python3 - my-project`
  - Flags: `--no-venv` (skip env entirely; implies `--no-install`), `--no-install` (env without pip install), `--version V` (pin a specific release).
- **`.starter-manifest.json`**: declarative whitelist of files and directories that belong to a fresh project. Single source of truth for what makes up "a Nori starter" — the installer reads it from each release zip, so the manifest evolves alongside the framework.

### Changed
- **README Quick Start uses the installer instead of `git clone`.** Cloning the repo brought along framework dev files (`README.md`, `CHANGELOG.md`, `docs/`, `.github/`, `mkdocs.yml`, `tests/`, `.firebaserc`, etc.) that didn't belong in user projects, and inherited the framework's git history as the starting point. The installer is now the recommended path; cloning remains supported for framework contributors.

---

## [1.9.0] — 2026-04-24

### Added
- **`old()` Jinja helper for form re-population.** Pair `flash_old(request, form)` in the controller (after a failed `validate()`) with `{{ old('field') }}` in the template to keep what the user typed across validation errors. Sensitive fields (`password`, `password_confirmation`, `current_password`, `new_password`) are stripped from the flash by default; pass `exclude=` to override. Lives in `core/http/old.py`, registered as a Jinja global. See `docs/forms_validation.md`.
- **`python3 nori.py shell`**: async REPL via `python -m asyncio` with Tortoise pre-booted against `settings.TORTOISE_ORM` and every model in `core.registry` bound as a top-level name. `await User.all()` works at the prompt with no imports or setup. See `docs/cli.md`.
- **CLI command tests** (`tests/test_core/test_cli.py`): 16 tests covering `make:controller`, `make:model`, `make:seeder`, `migrate:init` (the regression we caught in 1.8.1), `migrate:make`, `migrate:upgrade`, `migrate:downgrade`, `migrate:fresh` DEBUG safety, and `framework:version`. Closes the test gap that let the `migrate:init` bug ship in 1.8.0. Suite: 558 → 585 total.
- **11 new tests** for the `old()` helper covering flash, default-exclude, custom-exclude, and Jinja-global integration paths.

---

## [1.8.1] — 2026-04-24

### Fixed
- **`migrate:init` now initializes both apps**. The previous implementation ran `aerich init-db` once with no `--app` flag, which only initialized the first app from `pyproject.toml` (`framework`) and silently left `models` without migrations or tables. The user app would appear "missing" until they manually invoked `aerich --app models init-db`. Fixed to loop over `('framework', 'models')` and run `init-db` per app. The loop is idempotent — apps with existing migration files are skipped, so re-running `migrate:init` is now safe.

### Docs
- Added an engine-consistency warning to `docs/database.md`: aerich migrations are engine-specific, so dev should mirror prod (don't generate against SQLite locally if you deploy to MySQL). Points users to the bundled `docker-compose.yml` for a local MySQL.

---

## [1.8.0] — 2026-04-24

### Fixed
- **`tomlkit` missing from `requirements.nori.txt`**: Aerich 0.9.2 imports `tomlkit` at runtime to read/write `pyproject.toml` during `migrate:init` / `migrate`, but does not list it as a transitive dependency. Pinning `tomlkit>=0.13` directly avoids `ModuleNotFoundError` on first install.

### Changed (BREAKING)
- **`migrations/framework/` is now user-owned, generated locally against each site's DB engine.** It has been removed from `_FRAMEWORK_DIRS` — `framework:update` no longer ships, replaces, or backs up its contents. The pre-generated `0_20260328_init.py` (which hard-coded SQLite-only `AUTOINCREMENT` syntax and broke MySQL / PostgreSQL setups with error 1064) has been removed from the repo. Each site now generates its own framework migrations via `python3 nori.py migrate:init` on first install, and via `migrate:make ... --app framework` whenever the framework adds new models.

### Docs
- Updated `docs/getting_started.md`, `docs/database.md`, and `docs/cli.md` to reflect the new flow (engine-specific migrations, `migrate:init` as a mandatory first-run step).

### Upgrade note

**For sites that successfully applied the old SQLite migration** (DB engine = SQLite, or MySQL/Postgres deployment that happened to skip the broken migration somehow): no action needed. Your `migrations/framework/0_20260328_init.py` stays in place, your `aerich` table tracks it, and future `migrate:make --app framework` commands diff against the embedded `MODELS_STATE` correctly.

**For sites that never applied the old migration** (e.g. fresh checkout on MySQL where the migration crashed with error 1064 before being recorded): delete the broken file and regenerate:

```bash
rm rootsystem/application/migrations/framework/0_20260328_init.py
python3 nori.py migrate:init
```

This generates the initial framework migration adapted to your engine and applies it.

---

## [1.7.1] — 2026-04-24

### Fixed
- **Dockerfile now copies `requirements.nori.txt`**: with the split introduced in 1.7.0, the `Dockerfile` template was still doing `COPY requirements.txt .`, which caused `pip install -r requirements.txt` to fail in the builder stage with `ERROR: -r requirements.nori.txt not found`. The COPY line now includes both files.

### Docs
- Added a **Docker** section to `docs/dependencies.md` documenting the required `COPY` line and the one-line manual fix for sites with a pre-1.7.1 `Dockerfile`.

### Upgrade note
If your site was created on Nori ≤ 1.7.0 and you use Docker, edit your `Dockerfile` in the builder stage:

```dockerfile
# before
COPY requirements.txt .

# after
COPY requirements.txt requirements.nori.txt ./
```

Nothing else in the build changes. The `Dockerfile` lives in user-land (not touched by `framework:update`) and is too opinionated per-site for the patch system to safely auto-edit it.

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
