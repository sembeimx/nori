from __future__ import annotations

import asyncio
from datetime import timedelta
from tortoise.timezone import now
from typing import Callable, Any
from core.conf import config
from core.logger import get_logger
from core.registry import get_model
from core.tasks import background

_log = get_logger('queue')
_DRIVERS = {}

def register_queue_driver(name: str, handler: Callable):
    _DRIVERS[name] = handler

async def push(func_path: str, *args, queue: str = 'default', delay: int = 0, **kwargs):
    driver_name = config.get('QUEUE_DRIVER', 'memory')
    handler = _DRIVERS.get(driver_name, _DRIVERS.get('memory'))
    payload = {"func": func_path, "args": args, "kwargs": kwargs}
    await handler(queue, payload, delay=delay)

async def _memory_handler(queue: str, payload: dict, delay: int = 0):
    from core.queue_worker import execute_payload
    if delay > 0:
        async def _delayed():
            await asyncio.sleep(delay)
            await execute_payload(payload)
        background(_delayed)
    else:
        background(execute_payload, payload)

async def _db_handler(queue: str, payload: dict, delay: int = 0):
    if not config.get('DB_ENABLED', False):
        return await _memory_handler(queue, payload, delay)
    Job = get_model('Job')
    available_at = now() + timedelta(seconds=delay) if delay > 0 else now()
    await Job.create(queue=queue, payload=payload, available_at=available_at)

register_queue_driver('memory', _memory_handler)
register_queue_driver('database', _db_handler)
