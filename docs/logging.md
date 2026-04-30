# Logging

Nori provides a production-grade logging system under the `nori` namespace, with support for text and JSON formatters, file rotation, and environment-based configuration.

Logging is invisible until something breaks. Then it is everything. Text format is for humans reading terminals. JSON format is for machines — log aggregators like Datadog or CloudWatch parse structured logs automatically.

---

## Configuration (.env)

| Var | Values | Default |
|-----|--------|---------|
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | `DEBUG` if `DEBUG=true`, else `INFO` |
| `LOG_FORMAT` | `text`, `json` | `text` |
| `LOG_FILE` | File path (optional) | None (stdout only) |

---

## Basic Usage

```python
from core.logger import get_logger

log = get_logger('mymodule')  # Creates 'nori.mymodule' logger

log.debug('Processing item %d', item_id)
log.info('User %d logged in', user_id)
log.warning('Rate limit approaching for IP %s', ip)
log.error('Failed to send email to %s', email)
log.exception('Unexpected error')  # Includes traceback
```

`get_logger(name)` returns a child logger under the `nori` namespace. Calling `get_logger()` without arguments returns the root `nori` logger.

---

## Output Formats

### Text (default)

```
[2026-03-26 14:30:00] INFO - nori.mymodule: User 42 logged in
```

Human-readable, suitable for development and simple production setups.

### JSON (`LOG_FORMAT=json`)

```json
{"timestamp": "2026-03-26T14:30:00.000Z", "level": "INFO", "logger": "nori.mymodule", "message": "User 42 logged in", "request_id": "abc-123"}
```

Structured output for log aggregators (Datadog, CloudWatch, ELK). Includes `request_id` when `RequestIdMiddleware` is active. The `exception` field is included when logging exceptions.

---

## File Rotation

When `LOG_FILE` is set, logs are written to both stdout and the file. File rotation is automatic:

- **Max size**: 10 MB per file
- **Backups**: 5 rotated files kept

```text
LOG_FILE=/var/log/nori/app.log
```

This produces: `app.log`, `app.log.1`, `app.log.2`, ..., `app.log.5`.

### Performance note

`RotatingFileHandler` performs synchronous disk I/O on every log emit and during rotation events. In practice this is microseconds per call (writes are buffered by the kernel) and rarely a measurable bottleneck — but it does run on the event loop, so heavy logging on a slow disk could nibble at request latency.

The recommended pattern for production deploys is **stdout-only logging** (leave `LOG_FILE` unset) and let your container orchestrator (Docker, Kubernetes, systemd) collect, rotate, and forward logs out-of-process. That way the application loop is never blocked by disk I/O, and log shipping is decoupled from the request path.

Use `LOG_FILE` for local development, single-VM deploys, or when you need a guaranteed on-disk record alongside stdout.

---

## Framework Loggers

Nori's internal modules use named loggers for targeted filtering:

| Logger | Used by |
|--------|---------|
| `nori.asgi` | Application startup, error handlers |
| `nori.bootstrap` | User bootstrap hook (`bootstrap.py`) errors |
| `nori.audit` | Audit log entries |
| `nori.tasks` | Background task errors |
| `nori.ws` | WebSocket handler errors |
| `nori.csrf` | CSRF middleware |
| `nori.throttle` | Rate limiting |
| `nori.mail` | Email dispatcher |
| `nori.upload` | File upload validation |
| `nori.auth` | Authentication, login guard, permissions |
| `nori.inject` | Dependency injection warnings |
| `nori.search` | Search dispatcher |
| `nori.cache` | Cache backend initialization |
| `nori.queue` | Queue dispatcher and worker |

You can adjust the level of any individual logger in your application code:

```python
import logging

logging.getLogger('nori.mail').setLevel(logging.WARNING)
```
