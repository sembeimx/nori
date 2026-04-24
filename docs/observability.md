# Observability

Nori does not bundle Sentry, Datadog, or OpenTelemetry in the core — those SDKs change fast and carry weight, and not every site wants the same one. What Nori provides is a single, correctly-timed extension point so you can plug any observability SDK into your site in a few lines.

That extension point is the **bootstrap hook**.

---

## Why timing matters

Observability SDKs work by patching third-party libraries at import time — Sentry hooks into `httpx`, `asyncpg`, `starlette`; OpenTelemetry auto-instruments dozens of libraries. If you call `sentry_sdk.init()` after those libraries have been imported, the patches are silently incomplete and some telemetry never fires.

The bootstrap hook runs **before Nori imports Starlette, Tortoise, or any other instrumentable library**, so every subsequent import sees the instrumented versions.

---

## Creating the hook

Create `rootsystem/application/bootstrap.py`:

```python
def bootstrap() -> None:
    # Your init code goes here — runs before the framework loads.
    pass
```

That is the entire contract:

- The file is **optional**. If it does not exist, Nori starts normally.
- Define a top-level function named `bootstrap` that takes no arguments.
- If `bootstrap()` raises, a warning is logged on the `nori.bootstrap` logger and the app still starts — a broken hook never crashes the server.

The file lives in user-land. `framework:update` never touches it.

---

## Recipe: Sentry

### 1. Install the SDK

```bash
pip install sentry-sdk
```

### 2. Create `rootsystem/application/bootstrap.py`

```python
import os


def bootstrap() -> None:
    dsn = os.environ.get('SENTRY_DSN')
    if not dsn:
        return

    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get('SENTRY_ENV', 'development'),
        release=os.environ.get('RELEASE_SHA'),
        traces_sample_rate=float(os.environ.get('SENTRY_TRACES_RATE', '0.1')),
        send_default_pii=False,
    )
```

### 3. Set the environment variables

```text
SENTRY_DSN=https://<key>@<org>.ingest.sentry.io/<project>
SENTRY_ENV=production
SENTRY_TRACES_RATE=0.1
RELEASE_SHA=<commit-sha>
```

That is it. Sentry picks up uncaught exceptions from controllers and middleware, traces requests, and ties reports to your release SHA.

### Notes

- **Sensitive data**: `send_default_pii=False` is the safe default. Nori already exposes `protected_fields` on models to keep password hashes and tokens out of `to_dict()`; Sentry complements that by not capturing request bodies or cookies unless you opt in.
- **Sample rate**: `1.0` captures every transaction (expensive). `0.1` captures 10%. Tune based on traffic and your Sentry quota.
- **Skip in tests**: the `if not dsn: return` guard keeps Sentry silent when `SENTRY_DSN` is unset — perfect for CI and local development.

---

## Other integrations

The same pattern applies to Datadog (`ddtrace.patch_all()`), OpenTelemetry (`opentelemetry.sdk.trace` setup), New Relic, Honeycomb, and anything else that needs early initialization. Put the setup inside `bootstrap()` and configure via environment variables — the hook is a plain Python function, so you own what happens inside.

For Datadog specifically, the `ddtrace-run` wrapper is also an option and skips the bootstrap hook entirely:

```bash
ddtrace-run uvicorn asgi:app
```

Use whichever fits your deployment.

---

## Upgrading an existing site

If your site runs Nori ≤ 1.5.x, the upgrade to 1.6.0 is a two-step:

```bash
python3 nori.py framework:update             # step 1 — brings in v1.6.0
python3 nori.py framework:update --force     # step 2 — applies patches
```

### Why two steps?

The patch system itself ships in 1.6.0. When you run `framework:update` on an older release, the code that executes is still the OLD `core/cli.py` — it has already been loaded into memory by the Python interpreter. It downloads and replaces the files on disk with 1.6.0, but the running process keeps executing the old logic, which does not know about patches.

The second run (`--force`) is executed by the newly installed 1.6.0 `cli.py`, so the patcher actually fires and you will see:

```text
  Applying patches...
    ✓ asgi.py: added bootstrap hook
```

This is a **one-time** quirk for the first upgrade to a release that introduces the patch system. From 1.6.x onwards, patches run automatically on every update.

The patch is idempotent — running it repeatedly is a no-op. A timestamped backup of the pre-patch `asgi.py` lives under `rootsystem/.framework_backups/` if you ever need to inspect it.
