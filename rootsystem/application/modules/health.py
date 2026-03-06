"""
Health check endpoint for monitoring and orchestration (k8s, load balancers).

    GET /health  ->  {"status": "ok", "db": "ok"} | 503
"""
from starlette.requests import Request
from starlette.responses import JSONResponse
from tortoise import Tortoise
from core.logger import get_logger

_log = get_logger('health')


class HealthController:

    async def check(self, request: Request) -> JSONResponse:
        """Lightweight health check: verifies DB connectivity."""
        result = {'status': 'ok', 'db': 'ok'}
        status = 200

        try:
            conn = Tortoise.get_connection('default')
            await conn.execute_query("SELECT 1")
        except Exception as exc:
            _log.error("Health check DB failure: %s", exc)
            result['db'] = 'error'
            result['status'] = 'degraded'
            status = 503

        return JSONResponse(result, status_code=status)
