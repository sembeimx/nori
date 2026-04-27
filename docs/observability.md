# Observability

Nori does not bundle Sentry, Datadog, or OpenTelemetry in the core — those SDKs change fast and carry weight, and not every site wants the same one. What Nori provides is a single, correctly-timed extension point so you can plug any observability SDK into your site in a few lines.

That extension point is the **bootstrap hook**.

---

## Why timing matters

Observability SDKs work by patching third-party libraries at import time — Sentry hooks into `httpx`, `asyncpg`, `starlette`; OpenTelemetry auto-instruments dozens of libraries. If you call `sentry_sdk.init()` *after* those libraries have been imported, the patches are silently incomplete and some telemetry never fires.

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

## Recipe: OpenTelemetry

OpenTelemetry is the vendor-neutral standard. Same trace data goes to Jaeger, Honeycomb, Datadog, New Relic, Grafana Tempo, or any other OTLP-compatible backend.

### 1. Install the SDK and the auto-instrumentation packages

```bash
pip install \
    opentelemetry-api \
    opentelemetry-sdk \
    opentelemetry-exporter-otlp \
    opentelemetry-instrumentation-starlette \
    opentelemetry-instrumentation-asyncpg \
    opentelemetry-instrumentation-httpx
```

Pick the instrumentation packages that match the libraries your site actually uses. `asyncpg` for Postgres, `aiomysql` / `asyncmy` for MySQL, `redis` if you use the Redis cache or throttle backend, `httpx` for outbound requests.

### 2. Create `rootsystem/application/bootstrap.py`

```python
import os


def bootstrap() -> None:
    endpoint = os.environ.get('OTEL_EXPORTER_OTLP_ENDPOINT')
    if not endpoint:
        return

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    # Configure the global tracer provider.
    resource = Resource.create({
        SERVICE_NAME: os.environ.get('OTEL_SERVICE_NAME', 'nori-app'),
    })
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)

    # Auto-instrument the libraries that ship telemetry.
    from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.starlette import StarletteInstrumentor

    AsyncPGInstrumentor().instrument()
    HTTPXClientInstrumentor().instrument()
    StarletteInstrumentor.instrument()  # Starlette uses a class method.
```

### 3. Set the environment variables

```text
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
OTEL_SERVICE_NAME=my-nori-app
```

You also need an OTLP collector running somewhere — typically the [OpenTelemetry Collector](https://opentelemetry.io/docs/collector/) deployed alongside your app, forwarding to your backend of choice.

### Notes

- `StarletteInstrumentor.instrument()` wraps every request in a span tagged with the route, method, and status. Combined with the `asyncpg` instrumentation, you get a flame graph showing exactly which SQL query inside a request is slow.
- Order does not matter inside `bootstrap()` — instrumentation hooks register globally and apply when the libraries are imported by Nori afterwards.
- `BatchSpanProcessor` buffers spans and flushes asynchronously. `SimpleSpanProcessor` flushes per-span (synchronous, slower, useful for debugging only).

---

## Recipe: Datadog

Datadog ships its own SDK (`ddtrace`) that auto-instruments most popular Python libraries with one call.

### Option A — bootstrap hook

```bash
pip install ddtrace
```

```python
# rootsystem/application/bootstrap.py
import os


def bootstrap() -> None:
    if not os.environ.get('DD_TRACE_ENABLED', '').lower() in ('1', 'true', 'yes'):
        return

    from ddtrace import patch_all
    patch_all()  # Patches starlette, asyncpg, httpx, redis, and everything else ddtrace knows about.
```

### Option B — `ddtrace-run` wrapper

Datadog also ships a wrapper that patches before any application code runs, skipping the bootstrap hook entirely:

```bash
ddtrace-run uvicorn asgi:app --host 0.0.0.0 --port 8000
```

Use Option A if you want the patching decision to be visible in your codebase. Use Option B if your deployment platform standardises on `ddtrace-run` (Datadog's Kubernetes integration uses it by default).

### Environment

Datadog reads agent connection info from environment variables — typically:

```text
DD_TRACE_ENABLED=true
DD_AGENT_HOST=datadog-agent
DD_TRACE_AGENT_PORT=8126
DD_SERVICE=my-nori-app
DD_ENV=production
DD_VERSION=<commit-sha>
```

---

## Correlating Request-ID with traces

Since v1.11.0 Nori automatically attaches a `request_id` to every log record under an HTTP request (including from `asyncio.create_task` background work). You can copy that same ID onto observability spans so a single trace correlates logs ↔ spans ↔ external service calls.

The current ID is available via `core.http.request_id.get_request_id()`:

```python
from core.http.request_id import get_request_id

rid = get_request_id()  # str | None
```

### OpenTelemetry — copy as a span attribute

Wrap your handler entry points (or use a Starlette middleware after `RequestIdMiddleware`) to tag the active span:

```python
from opentelemetry import trace
from core.http.request_id import get_request_id


def tag_current_span_with_request_id() -> None:
    span = trace.get_current_span()
    rid = get_request_id()
    if span and rid:
        span.set_attribute('nori.request_id', rid)
```

Now every span produced under that request carries the same `nori.request_id` attribute as your logs, so you can pivot from a slow trace in Jaeger to the matching log lines in Loki/Elasticsearch with one query.

### Sentry — set as a tag

```python
import sentry_sdk
from core.http.request_id import get_request_id


def tag_sentry_with_request_id() -> None:
    rid = get_request_id()
    if rid:
        sentry_sdk.set_tag('request_id', rid)
```

Call this from a small middleware that runs after `RequestIdMiddleware`. Sentry then groups errors by `request_id` and surfaces it on every event.

---

## Verifying the hook fires

Add a debug log inside `bootstrap()`:

```python
def bootstrap() -> None:
    import logging
    logging.getLogger('nori.bootstrap').warning('bootstrap fired')
    # ... rest of your init ...
```

Run `python3 nori.py serve` — you should see `bootstrap fired` before any other startup line. If you do not, the file is in the wrong location (it must be `rootsystem/application/bootstrap.py`) or the function is not named `bootstrap`.

---

## When NOT to use the hook

- **Pure logging configuration** (changing levels, adding handlers) belongs in `core.logger` configuration via the `LOG_LEVEL` / `LOG_FORMAT` / `LOG_FILE` environment variables, not the bootstrap hook.
- **Database connection pooling** is owned by Tortoise ORM via `settings.TORTOISE_ORM`. Don't pre-connect inside `bootstrap()`.
- **App routes or middleware** belong in `routes.py` and `asgi.py` — the bootstrap hook is for *third-party SDK initialization*, not application wiring.

If you find yourself reaching for the hook for anything other than instrumentation, the answer is probably one of the dedicated extension points instead.
