# Background Tasks & Queues

Nori provides two ways to handle background operations:
1.  **Starlette BackgroundTasks** (Volatile, in-process)
2.  **Persistent Job Queues** (Database-backed, survives restarts)

Volatile tasks are fast and simple — fire and forget. Persistent queues are slower but survive restarts and retries. We give you both because the tradeoff depends on the job, not the framework.

---

## 1. Volatile Background Tasks (`background`)

Uses Starlette's `BackgroundTask`. Ideal for quick, non-critical tasks like sending a notification or indexing a search document where losing the task on a server restart is acceptable.

```python
from core.tasks import background, background_tasks, run_in_background

# Option 1: Create a single task, pass it to a response
task = background(send_welcome_email, user.email, user.name)
return JSONResponse({'ok': True}, background=task)

# Option 2: Attach a task to an existing response
response = JSONResponse({'ok': True})
return run_in_background(response, send_welcome_email, user.email)

# Option 3: Multiple tasks on a single response
tasks = background_tasks(
    (send_welcome_email, (user.email, user.name), {}),
    (index_user_search, (user.id,), {}),
)
return JSONResponse({'ok': True}, background=tasks)
```

Each element in `background_tasks()` is a `(func, args_tuple, kwargs_dict)` triple.

---

## 2. Persistent Queues (`push`)

Nori features a robust, multi-driver persistent queue system. Jobs are stored in a database or Redis and processed by a background worker. **Use this for critical tasks like bulk emails, PDF generation, or heavy processing.**

### Key Robustness Features
- **Atomic Locking**: Only one worker processes a job at a time. The database driver uses an atomic `UPDATE ... WHERE reserved_at IS NULL` to reserve a job; the Redis driver promotes delayed jobs via a Lua `EVAL` so `ZRANGEBYSCORE + LPUSH + ZREM` is a single atomic operation across the worker pool — no double-execution under multiple workers.
- **Exponential Backoff**: If a job fails, the next attempt is delayed by `(attempts⁴) × 15` seconds: ~15s → ~4m → ~20m → ~1h → ~3h. This gives external services time to recover.
- **Dead Letters**: After **5 failed attempts**, the job is marked with `failed_at` and stopped for manual inspection.
- **Graceful Shutdown**: The worker finishes the current job before exiting on `SIGINT`/`SIGTERM`.

### Configuration (.env)

| Variable | Values | Description |
| :--- | :--- | :--- |
| `QUEUE_DRIVER` | `memory`, `database`, `redis` | `database` or `redis` for production. |
| `REDIS_URL` | Redis connection string | Required if using the `redis` driver. Default: `redis://localhost:6379` |

### Security: module allow-list

The worker resolves the function to execute via `importlib.import_module(mod_path) + getattr(module, func_name)`. **Without restrictions, anyone with write access to the queue store (a SQL injection point that reaches the `jobs` table, or an unauthenticated Redis instance) could push a payload like `{"func": "os:system", "args": ["..."]}` and trigger arbitrary code execution with the worker's privileges.**

Nori blocks this by checking `mod_path` against an allow-list of module prefixes before importing. The default — set in `settings.py` — covers the conventional Nori locations:

```python
QUEUE_ALLOWED_MODULES = ['modules.', 'services.', 'app.', 'tasks.']
```

| Prefix | Intended for |
| :--- | :--- |
| `modules.` | Tasks living next to controllers (`modules.mail`, `modules.reports`, ...) |
| `services.` | Service drivers (mail, storage, search) |
| `app.` | Projects that nest jobs under `app/tasks/` or similar |
| `tasks.` | Projects that put background tasks in a top-level `tasks/` package |

If your jobs live elsewhere, extend the list — each prefix should end with a `.` so a name like `modules` does not accidentally match `modules_evil`. Nori normalizes a missing trailing dot automatically, so `'my_jobs'` and `'my_jobs.'` are equivalent.

A payload whose `func` does not match any allowed prefix is rejected with `PermissionError` **before** the import. The rejection counts as a job failure, so the existing retry/backoff and dead-letter logic still apply — a poisoned job does not stall the worker.

### Driver Comparison

| Feature | `memory` | `database` | `redis` |
| :--- | :--- | :--- | :--- |
| **Persistence** | No | Yes (DB) | Yes (Redis) |
| **Job pickup** | Instant | Polling (3s) | Near-instant (BRPOP) |
| **Shared across workers** | No | Yes | Yes |
| **Delayed jobs** | `asyncio.sleep` | `available_at` column | Sorted set (ZADD) |
| **Dead letters** | No | `failed_at` column | `nori:queue:{name}:failed` list |
| **Requires** | Nothing | DB + `Job` model | `redis[hiredis]` package |

### Sending a Job to the Queue

```python
from core import push

async def store(self, request):
    # Syntax: await push('module.path:function_name', *args, delay=0, **kwargs)
    
    # Simple push
    await push('modules.mail:send_welcome', email=user.email)
    
    # Delayed push (send in 1 hour)
    await push('modules.reminder:notify', user.id, delay=3600)
    
    return JSONResponse({'status': 'Job queued'})
```

### Running the Worker

To process the queued jobs, run the Nori worker in a separate process (ideal for a sidecar container or systemd service):

```bash
python3 nori.py queue:work
```

You can specify a custom queue name (default is `default`):
```bash
python3 nori.py queue:work --name high_priority
```

---

## Error Handling

### In Volatile Tasks (`background`)
- The error is **logged** via `nori.tasks` logger.
- The exception is **not re-raised**.

### In Persistent Queues (`push`)
- The error is **logged** via `nori.queue` logger.
- The `attempts` counter is incremented.
- The next retry is scheduled with **exponential backoff**.
- After **5 failures**, it is marked as **failed** (Dead Letter).

---

## When to use which?

| Feature | `background()` | `push()` |
| :--- | :--- | :--- |
| **Persistence** | No (Lost on restart) | **Yes** (Stored in DB or Redis) |
| **Retries** | No | **Yes** (Exponential backoff) |
| **Worker process** | Not needed | **Required** (`queue:work`) |
| **Atomic** | No | **Yes** (One worker per job) |
| **Best for** | Logs, fast notifications | Emails, PDFs, Heavy Syncing |
