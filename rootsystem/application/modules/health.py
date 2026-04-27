"""
Health check endpoint for monitoring and orchestration (k8s, load balancers).

    GET /health  ->  {"status": "ok", "db": "ok", "cache": "ok", "throttle": "ok"}
                  -> 503 with {"status": "degraded", ...} on any failure

Probes:
- Database (when ``DB_ENABLED``): ``SELECT 1`` against the default connection.
- Cache backend: ``verify()`` (no-op for memory, ping for Redis).
- Throttle backend: ``verify()`` (no-op for memory, ping for Redis).

Memory backends always report "ok" (their ``verify()`` is a no-op). Redis
backends report "error" with a 503 if unreachable — the same condition that
fail-fasts the app at startup, but reported continuously here so orchestrators
can pull the node out of rotation if Redis goes down post-boot.
"""

from __future__ import annotations

import settings
from core.cache import get_backend as get_cache_backend
from core.http.throttle_backends import get_backend as get_throttle_backend
from core.logger import get_logger
from starlette.requests import Request
from starlette.responses import JSONResponse

_log = get_logger('health')


class HealthController:
    async def check(self, request: Request) -> JSONResponse:
        """Deep health check: DB, cache, throttle. 503 if any dependency is down."""
        result: dict[str, str] = {'status': 'ok'}
        status = 200

        if settings.DB_ENABLED:
            result['db'] = 'ok'
            try:
                from tortoise import Tortoise

                conn = Tortoise.get_connection('default')
                await conn.execute_query('SELECT 1')
            except Exception as exc:
                _log.error('Health check DB failure: %s', exc)
                result['db'] = 'error'
                result['status'] = 'degraded'
                status = 503

        result['cache'] = 'ok'
        try:
            await get_cache_backend().verify()
        except Exception as exc:
            _log.error('Health check cache failure: %s', exc)
            result['cache'] = 'error'
            result['status'] = 'degraded'
            status = 503

        result['throttle'] = 'ok'
        try:
            await get_throttle_backend().verify()
        except Exception as exc:
            _log.error('Health check throttle failure: %s', exc)
            result['throttle'] = 'error'
            result['status'] = 'degraded'
            status = 503

        return JSONResponse(result, status_code=status)
