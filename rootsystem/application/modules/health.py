"""
Health check endpoint for monitoring and orchestration (k8s, load balancers).

    GET /health  ->  {"status": "ok", "db": "ok"} | 503
"""

from __future__ import annotations

import settings
from core.logger import get_logger
from starlette.requests import Request
from starlette.responses import JSONResponse

_log = get_logger('health')


class HealthController:

    async def check(self, request: Request) -> JSONResponse:
        """Lightweight health check: verifies DB connectivity when enabled."""
        result = {'status': 'ok'}
        status = 200

        if settings.DB_ENABLED:
            result['db'] = 'ok'
            try:
                from tortoise import Tortoise
                conn = Tortoise.get_connection('default')
                await conn.execute_query("SELECT 1")
            except Exception as exc:
                _log.error("Health check DB failure: %s", exc)
                result['db'] = 'error'
                result['status'] = 'degraded'
                status = 503

        return JSONResponse(result, status_code=status)
