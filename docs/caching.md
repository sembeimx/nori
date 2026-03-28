# Caching

Nori provides a pluggable caching layer with TTL (time-to-live) support. Use it to cache expensive queries, computed values, or entire HTTP responses.

---

## Configuration (.env)

| Var | Values | Default |
|-----|--------|---------|
| `CACHE_BACKEND` | `memory`, `redis` | `memory` |
| `REDIS_URL` | Redis connection string | `redis://localhost:6379` |

The `memory` backend stores values in-process (fast, but not shared across workers). The `redis` backend shares cache across Gunicorn workers and Docker replicas.

---

## Convenience Functions

```python
from core.cache import cache_get, cache_set, cache_delete, cache_flush

# Store a value with a 5-minute TTL (default: 300 seconds)
await cache_set('user:42:profile', user_data, ttl=300)

# Retrieve — returns None if expired or missing
profile = await cache_get('user:42:profile')

# Delete a specific key
await cache_delete('user:42:profile')

# Flush the entire cache
await cache_flush()
```

---

## Response Caching Decorator

The `@cache_response` decorator caches the full HTTP response for `GET` requests. Non-GET requests pass through uncached. Only **successful responses (2xx)** are cached — error responses (4xx, 5xx) are never stored.

```python
from core.cache import cache_response

class ReportController:

    @cache_response(ttl=60)  # Cache for 60 seconds
    async def dashboard(self, request):
        # Expensive query — only runs once per TTL window
        stats = await compute_dashboard_stats()
        return JSONResponse(stats)
```

Cache keys are generated automatically from the request path and query string. You can customize the prefix:

```python
@cache_response(ttl=120, key_prefix='reports')
async def monthly(self, request):
    ...
```

---

## Backends

### MemoryCacheBackend (default)

In-process dictionary with TTL enforcement on read. Zero configuration, ideal for development and single-process deployments.

> **Production warning**: Expired entries are only evicted when read — unread keys remain in memory indefinitely. In long-running processes this can cause unbounded memory growth. Additionally, each Gunicorn worker maintains its own isolated cache, so state is not shared. **Use `redis` in production.**

### RedisCacheBackend

Requires `CACHE_BACKEND=redis` and a valid `REDIS_URL`. Uses Redis `SETEX` for atomic TTL. Shared across all workers. The Redis serializer handles common Python types (`datetime`, `date`, `UUID`, `Decimal`) automatically; other non-JSON-serializable types will raise `TypeError` instead of being silently converted.

### Direct Backend Access

For advanced use cases, you can access the backend instance directly:

```python
from core.cache import get_backend

backend = get_backend()
await backend.set('key', 'value', ttl=60)
```
