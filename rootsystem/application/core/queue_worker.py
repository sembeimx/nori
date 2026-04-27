from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import signal
import time
from datetime import timedelta

from tortoise.timezone import now

from core.conf import config
from core.logger import get_logger
from core.registry import get_model

_log = get_logger('queue')
MAX_ATTEMPTS = 5
_should_exit = False


def _handle_exit(sig, frame):
    global _should_exit
    _log.info("Shutdown signal received, finishing current job...")
    _should_exit = True


async def execute_payload(payload: dict):
    mod_path, func_name = payload['func'].split(':')
    module = importlib.import_module(mod_path)
    func = getattr(module, func_name)
    if inspect.iscoroutinefunction(func):
        await func(*payload.get('args', []), **payload.get('kwargs', {}))
    else:
        func(*payload.get('args', []), **payload.get('kwargs', {}))


async def work(queue_name: str = 'default', sleep: int = 3):
    """Start a queue worker. Dispatches to the correct driver automatically."""
    driver = config.get('QUEUE_DRIVER', 'memory')
    if driver == 'redis':
        await _work_redis(queue_name)
    else:
        await _work_database(queue_name, sleep)


async def _work_database(queue_name: str, sleep: int = 3):
    """Database-backed worker: polls the Job table."""
    Job = get_model('Job')
    global _should_exit

    _register_signals()
    _log.info("Queue worker started [driver=database, queue=%s, max_attempts=%d]", queue_name, MAX_ATTEMPTS)

    while not _should_exit:
        job = await Job.filter(
            queue=queue_name,
            reserved_at__isnull=True,
            available_at__lte=now(),
            failed_at__isnull=True
        ).first()

        if not job:
            await asyncio.sleep(sleep)
            continue

        affected = await Job.filter(id=job.id, reserved_at__isnull=True).update(reserved_at=now())
        if affected == 0:
            continue

        try:
            await execute_payload(job.payload)
            await job.delete()
        except Exception as e:
            job.attempts += 1
            job.reserved_at = None

            if job.attempts >= MAX_ATTEMPTS:
                job.failed_at = now()
                _log.error("Job %d failed permanently after %d attempts: %s", job.id, MAX_ATTEMPTS, e, exc_info=True)
            else:
                wait_seconds = (job.attempts ** 4) * 15
                job.available_at = now() + timedelta(seconds=wait_seconds)
                _log.warning("Job %d failed (attempt %d): %s. Retrying in %ds", job.id, job.attempts, e, wait_seconds, exc_info=True)

            await job.save()
            await asyncio.sleep(sleep)

    _log.info("Worker stopped cleanly.")


async def _work_redis(queue_name: str):
    """Redis-backed worker: uses BRPOP for near-instant job pickup."""
    from core.queue import _get_redis

    r = _get_redis()
    key = f'nori:queue:{queue_name}'
    delayed_key = f'{key}:delayed'
    failed_key = f'{key}:failed'

    _register_signals()
    _log.info("Queue worker started [driver=redis, queue=%s, max_attempts=%d]", queue_name, MAX_ATTEMPTS)

    global _should_exit
    while not _should_exit:
        # 1. Promote delayed jobs whose time has come
        ready = await r.zrangebyscore(delayed_key, '-inf', time.time())
        for item in ready:
            await r.lpush(key, item)
            await r.zrem(delayed_key, item)

        # 2. Block-pop the next job (1s timeout to check _should_exit)
        result = await r.brpop(key, timeout=1)
        if result is None:
            continue

        _, raw = result
        job_data = json.loads(raw)
        attempts = job_data.get('attempts', 0)

        try:
            await execute_payload(job_data)
        except Exception as e:
            attempts += 1
            job_data['attempts'] = attempts

            if attempts >= MAX_ATTEMPTS:
                job_data['failed_at'] = time.time()
                await r.lpush(failed_key, json.dumps(job_data))
                _log.error("Job failed permanently after %d attempts: %s", MAX_ATTEMPTS, e, exc_info=True)
            else:
                wait_seconds = (attempts ** 4) * 15
                await r.zadd(delayed_key, {json.dumps(job_data): time.time() + wait_seconds})
                _log.warning("Job failed (attempt %d): %s. Retrying in %ds", attempts, e, wait_seconds, exc_info=True)

    _log.info("Worker stopped cleanly.")


def _register_signals():
    """Register SIGINT/SIGTERM for graceful shutdown."""
    try:
        signal.signal(signal.SIGINT, _handle_exit)
        signal.signal(signal.SIGTERM, _handle_exit)
    except ValueError:
        pass
