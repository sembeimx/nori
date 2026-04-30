# Caching

Nori provides a pluggable caching layer with TTL (time-to-live) support. Use it to cache expensive queries, computed values, or entire HTTP responses.

A single `@cache_response(ttl=60)` on a dashboard endpoint can handle 100x more traffic without touching the database. Cache is the cheapest performance upgrade you can make.

---

## Configuration (.env)

| Var | Values | Default |
|-----|--------|---------|
| `CACHE_BACKEND` | `memory`, `redis` | `memory` |
| `CACHE_MAX_KEYS` | Integer (for memory backend) | `10000` |
| `REDIS_URL` | Redis connection string | `redis://localhost:6379` |

The `memory` backend stores values in-process using a **Least Recently Used (LRU)** eviction strategy. When the `CACHE_MAX_KEYS` limit is reached, the oldest/least used entries are automatically removed to prevent memory exhaustion.

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

## Atomic Primitives

For counters, rate limits, and any read-modify-write workflow, use these instead of `cache_get` + `cache_set` — the latter is a TOCTOU race that lets concurrent callers clobber each other.

```python
from core.cache import cache_incr, cache_atomic_update

# Atomic counter — survives concurrent callers without a lock
attempts = await cache_incr('login:user@example.com:attempts', ttl=3600)

# Read-modify-write under the cache lock; `fn` must be idempotent
new_state = await cache_atomic_update(
    'order:42:status',
    lambda current: {**(current or {}), 'updated_at': time.time()},
    ttl=300,
)
```

`cache_incr` returns the new integer value. The TTL is set only on first increment (when the result is 1) so the window is predictable.

`cache_atomic_update` retries under contention on the Redis backend (`WatchError`); pass an idempotent `fn`. Use it when the value is composite or non-integer; otherwise prefer `cache_incr`.

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

The memory backend works for development and single-process deployments. In production with Gunicorn, each worker has its own memory — use Redis so cache and rate limits are shared across all workers.

### MemoryCacheBackend (default)

In-process LRU cache with TTL enforcement on read. Zero configuration, ideal for development and single-process deployments.

- **LRU eviction**: When the store reaches `max_keys` (default: 10,000), the least-recently-used entry is evicted on insert. Reads and updates refresh an entry's position.
- **Configurable limit**: Set `CACHE_MAX_KEYS` in `.env` to override the default (e.g., `CACHE_MAX_KEYS=50000`).
- **TTL expiry**: Expired entries are evicted lazily on read.

> **Production note**: Each Gunicorn worker maintains its own isolated cache, so state is not shared across workers. **Use `redis` in production** for shared cache and rate limiting.

### RedisCacheBackend

Requires `CACHE_BACKEND=redis` and a valid `REDIS_URL`. Uses Redis `SETEX` for atomic TTL. Shared across all workers. The Redis serializer handles common Python types (`datetime`, `date`, `UUID`, `Decimal`) automatically; other non-JSON-serializable types will raise `TypeError` instead of being silently converted.

### Direct Backend Access

For advanced use cases, you can access the backend instance directly:

```python
from core.cache import get_backend

backend = get_backend()
await backend.set('key', 'value', ttl=60)
```
