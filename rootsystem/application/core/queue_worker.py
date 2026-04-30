"""Queue worker loop: pulls jobs from the configured driver and executes them."""

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

# Default allow-list of module prefixes whose functions can be executed from
# the queue. Anything not matching one of these is rejected before import,
# so a payload like `os:system` from a compromised queue store cannot run.
# Override via `settings.QUEUE_ALLOWED_MODULES`.
DEFAULT_ALLOWED_MODULES = ('modules.', 'services.', 'app.', 'tasks.')


def _handle_exit(sig, frame):
    global _should_exit
    _log.info('Shutdown signal received, finishing current job...')
    _should_exit = True


def _normalize_prefix(prefix: str) -> str:
    return prefix if prefix.endswith('.') else prefix + '.'


def _assert_allowed_module(mod_path: str) -> None:
    """Reject queue payloads whose module path is outside the allow-list.

    Without this check, anyone with write access to the queue store
    (DB row, Redis list) could push `{"func": "os:system", "args": [...]}`
    and the worker would import-and-call it. The allow-list is the
    primary defence — DB/Redis ACLs are the second.
    """
    raw = config.get('QUEUE_ALLOWED_MODULES', list(DEFAULT_ALLOWED_MODULES))
    allowed = tuple(_normalize_prefix(p) for p in raw)
    if not any(mod_path.startswith(p) for p in allowed):
        raise PermissionError(
            f'Refusing to import {mod_path!r}: not in QUEUE_ALLOWED_MODULES. '
            f'Allowed prefixes: {list(allowed)}. '
            f'Add the module prefix (with trailing dot) to '
            f'QUEUE_ALLOWED_MODULES in settings.py to extend the list.'
        )


async def execute_payload(payload: dict):
    mod_path, func_name = payload['func'].split(':')
    _assert_allowed_module(mod_path)
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
    _log.info('Queue worker started [driver=database, queue=%s, max_attempts=%d]', queue_name, MAX_ATTEMPTS)

    while not _should_exit:
        job = await Job.filter(
            queue=queue_name, reserved_at__isnull=True, available_at__lte=now(), failed_at__isnull=True
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
                _log.error('Job %d failed permanently after %d attempts: %s', job.id, MAX_ATTEMPTS, e, exc_info=True)
            else:
                wait_seconds = (job.attempts**4) * 15
                job.available_at = now() + timedelta(seconds=wait_seconds)
                _log.warning(
                    'Job %d failed (attempt %d): %s. Retrying in %ds',
                    job.id,
                    job.attempts,
                    e,
                    wait_seconds,
                    exc_info=True,
                )

            await job.save()
            await asyncio.sleep(sleep)

    _log.info('Worker stopped cleanly.')


# Atomic promotion of delayed Redis jobs whose score is <= now.
# Without this, two workers can each ZRANGEBYSCORE the same set of items
# before either of them ZREMs, then both LPUSH the same job — the worker
# pool ends up processing duplicates. Redis runs Lua scripts on a single
# thread, so wrapping the read+lpush+zrem cycle in EVAL makes the whole
# promotion atomic across workers.
_PROMOTE_DELAYED_LUA = """
local items = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
for i, item in ipairs(items) do
    redis.call('LPUSH', KEYS[2], item)
    redis.call('ZREM', KEYS[1], item)
end
return #items
"""


async def _work_redis(queue_name: str):
    """Redis-backed worker: uses BRPOP for near-instant job pickup."""
    from core.queue import _get_redis

    r = _get_redis()
    key = f'nori:queue:{queue_name}'
    delayed_key = f'{key}:delayed'
    failed_key = f'{key}:failed'

    _register_signals()
    _log.info('Queue worker started [driver=redis, queue=%s, max_attempts=%d]', queue_name, MAX_ATTEMPTS)

    global _should_exit
    while not _should_exit:
        # 1. Promote delayed jobs whose time has come — atomic (see Lua above)
        await r.eval(_PROMOTE_DELAYED_LUA, 2, delayed_key, key, time.time())

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
                _log.error('Job failed permanently after %d attempts: %s', MAX_ATTEMPTS, e, exc_info=True)
            else:
                wait_seconds = (attempts**4) * 15
                await r.zadd(delayed_key, {json.dumps(job_data): time.time() + wait_seconds})
                _log.warning('Job failed (attempt %d): %s. Retrying in %ds', attempts, e, wait_seconds, exc_info=True)

    _log.info('Worker stopped cleanly.')


def _register_signals():
    """Register SIGINT/SIGTERM for graceful shutdown."""
    try:
        signal.signal(signal.SIGINT, _handle_exit)
        signal.signal(signal.SIGTERM, _handle_exit)
    except ValueError:
        pass
