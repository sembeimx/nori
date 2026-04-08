# Changelog

All notable changes to Nori are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/).

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

[1.2.3]: https://github.com/sembeimx/nori/releases/tag/v1.2.3
[1.2.2]: https://github.com/sembeimx/nori/releases/tag/v1.2.2
[1.2.1]: https://github.com/sembeimx/nori/releases/tag/v1.2.1
