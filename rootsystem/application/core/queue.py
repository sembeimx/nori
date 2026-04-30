"""Background job queue dispatcher with pluggable drivers (memory, Redis, db)."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from datetime import timedelta

from tortoise.timezone import now

from core.conf import config
from core.logger import get_logger
from core.registry import get_model

_log = get_logger('queue')
_DRIVERS = {}

# Strong references to in-flight memory-driver tasks. ``asyncio.create_task``
# returns a Task that the event loop holds only by weak reference, so an
# unreferenced task can be garbage-collected mid-execution — particularly
# during a long ``await asyncio.sleep(delay)``, when nothing on the call
# stack pins the frame. Without this set a delayed welcome-mail dispatched
# via ``push('mail.send', delay=30)`` would silently disappear. Mirrors
# ``core.audit._pending_tasks``.
_memory_tasks: set[asyncio.Task] = set()

# Bounded concurrency cap for the memory driver. Module-level
# instantiation of ``asyncio.BoundedSemaphore`` would bind to whichever
# loop is running at import time (typically none — Python 3.10+ raises
# ``DeprecationWarning`` and 3.12+ outright errors), so the semaphore is
# lazy-initialised on first dispatch. By that point the ASGI lifespan is
# active and ``asyncio.get_running_loop()`` returns the loop we want.
#
# The default of 32 mirrors the default ``asyncio.to_thread`` worker
# count (Python 3.8+ ``ThreadPoolExecutor(max_workers=min(32, ...))``),
# so a burst of sync queue jobs cannot oversubscribe the thread pool by
# stacking more concurrent ``asyncio.to_thread`` callers than the pool
# can serve. Async jobs no longer fan out unbounded — pre-1.32 a
# ``push('async_func', ...)`` × 5000 spawned 5000 in-flight coroutines
# all at once; now at most 32 are inside ``execute_payload`` and the
# rest queue up at the semaphore.
#
# IMPORTANT: the semaphore guards EXECUTION, not pending dispatch. A
# task awaiting ``asyncio.sleep(delay)`` does NOT hold the semaphore;
# it acquires only just before ``execute_payload``. That keeps delayed
# jobs cheap (one Task each, idle until the timer fires) while still
# capping concurrent execution. If you need to cap the BACKLOG itself
# (i.e. push() refuses to enqueue when N tasks are pending), the
# right answer is the Redis or database driver — both are bounded by
# their respective storage shapes.
_memory_semaphore: asyncio.BoundedSemaphore | None = None


def _get_memory_semaphore() -> asyncio.BoundedSemaphore:
    """Lazy-init the BoundedSemaphore for the memory queue driver.

    Module-level instantiation would attempt to bind to a non-existent
    loop at import time. Tests that swap event loops between cases
    must reset ``_memory_semaphore`` to ``None`` (see ``conftest.py``)
    so the next test re-initialises against its own loop.
    """
    global _memory_semaphore
    if _memory_semaphore is None:
        cap = int(config.get('QUEUE_MEMORY_CONCURRENCY', 32))
        if cap < 1:
            raise ValueError(f'QUEUE_MEMORY_CONCURRENCY must be ≥ 1; got {cap}')
        _memory_semaphore = asyncio.BoundedSemaphore(cap)
    return _memory_semaphore


def register_queue_driver(name: str, handler: Callable):
    _DRIVERS[name] = handler


async def push(func_path: str, *args, queue: str = 'default', delay: int = 0, **kwargs):
    driver_name = config.get('QUEUE_DRIVER', 'memory')
    handler = _DRIVERS.get(driver_name, _DRIVERS.get('memory'))
    if handler is None:
        raise RuntimeError('No queue driver registered (memory driver missing)')
    payload = {'func': func_path, 'args': args, 'kwargs': kwargs}
    await handler(queue, payload, delay=delay)


async def _memory_handler(queue: str, payload: dict, delay: int = 0):
    from core.queue_worker import execute_payload

    semaphore = _get_memory_semaphore()

    async def _run():
        try:
            if delay > 0:
                await asyncio.sleep(delay)
            # Acquire AFTER the delay sleep — sleeping tasks are cheap
            # (just timer Tasks), the cap should bound concurrent
            # execution, not pending dispatch.
            async with semaphore:
                await execute_payload(payload)
        except Exception as exc:
            _log.error('Memory queue task failed: %s', exc, exc_info=True)

    task = asyncio.create_task(_run())
    _memory_tasks.add(task)
    task.add_done_callback(_memory_tasks.discard)


async def _db_handler(queue: str, payload: dict, delay: int = 0):
    if not config.get('DB_ENABLED', False):
        return await _memory_handler(queue, payload, delay)
    Job = get_model('Job')
    available_at = now() + timedelta(seconds=delay) if delay > 0 else now()
    await Job.create(queue=queue, payload=payload, available_at=available_at)


# ---------------------------------------------------------------------------
# Redis driver
# ---------------------------------------------------------------------------

_redis_client = None


def _get_redis():
    """Lazy-init a shared Redis connection for the queue."""
    global _redis_client
    if _redis_client is None:
        import redis.asyncio as aioredis

        redis_url = config.get('REDIS_URL', 'redis://localhost:6379')
        _redis_client = aioredis.from_url(redis_url, socket_connect_timeout=5)
    return _redis_client


async def _redis_handler(queue: str, payload: dict, delay: int = 0):
    """Push a job to a Redis list (immediate) or sorted set (delayed)."""
    r = _get_redis()
    key = f'nori:queue:{queue}'
    job = json.dumps({**payload, 'attempts': 0, 'queued_at': time.time()})

    if delay > 0:
        # Delayed jobs go to a sorted set, scored by execution time
        await r.zadd(f'{key}:delayed', {job: time.time() + delay})
    else:
        await r.lpush(key, job)


register_queue_driver('memory', _memory_handler)
register_queue_driver('database', _db_handler)
register_queue_driver('redis', _redis_handler)
