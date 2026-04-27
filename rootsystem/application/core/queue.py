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

    async def _run():
        try:
            if delay > 0:
                await asyncio.sleep(delay)
            await execute_payload(payload)
        except Exception as exc:
            _log.error('Memory queue task failed: %s', exc, exc_info=True)

    asyncio.create_task(_run())


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
