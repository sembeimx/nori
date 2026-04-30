"""Request rate limiting middleware with pluggable backends (memory, Redis)."""

from __future__ import annotations

import time
from collections.abc import Callable
from functools import wraps
from typing import Any

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from core.audit import get_client_ip
from core.http.throttle_backends import get_backend

_UNITS: dict[str, int] = {
    'second': 1,
    'minute': 60,
    'hour': 3600,
}


def _parse_rate(rate: str) -> tuple[int, int]:
    """Parse '10/minute' into (max_requests, window_seconds)."""
    parts = rate.split('/')
    if len(parts) != 2:
        raise ValueError(f"Invalid rate format: '{rate}'. Use 'N/unit' (e.g. '10/minute').")
    max_requests = int(parts[0])
    if max_requests <= 0:
        raise ValueError(f'Rate must be positive, got: {max_requests}')
    unit = parts[1].strip().lower()
    if unit not in _UNITS:
        raise ValueError(f"Unknown time unit: '{unit}'. Use: {', '.join(_UNITS)}.")
    return max_requests, _UNITS[unit]


def throttle(rate: str) -> Callable[..., Any]:
    """
    Rate-limit decorator for controller methods.

        @throttle('10/minute')
        async def create(self, request): ...
    """
    max_requests, window = _parse_rate(rate)

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(self: Any, request: Request, *args: Any, **kwargs: Any) -> Response:
            now = time.time()
            ip = get_client_ip(request) or 'unknown'
            key = f'{ip}:{request.url.path}'

            backend = get_backend()

            # Atomic check-and-add — see core/http/throttle_backends.py.
            # Splitting into get_timestamps + add_timestamp would race under
            # concurrency, letting parallel callers all read the same baseline
            # and bypass the limit.
            allowed, count, oldest = await backend.check_and_add(key, now, window, max_requests)

            reset = max(0, int(oldest + window - now)) if oldest else window

            if not allowed:
                headers = {
                    'X-RateLimit-Limit': str(max_requests),
                    'X-RateLimit-Remaining': '0',
                    'X-RateLimit-Reset': str(reset),
                }
                accept = request.headers.get('accept', '')
                if 'application/json' in accept:
                    return JSONResponse(
                        {'error': 'Too Many Requests'},
                        status_code=429,
                        headers=headers,
                    )
                return HTMLResponse(
                    '<h1>429 Too Many Requests</h1><p>Too many requests. Try again later.</p>',
                    status_code=429,
                    headers=headers,
                )

            response = await func(self, request, *args, **kwargs)

            response.headers['X-RateLimit-Limit'] = str(max_requests)
            response.headers['X-RateLimit-Remaining'] = str(max(0, max_requests - count))
            response.headers['X-RateLimit-Reset'] = str(reset)

            return response

        return wrapper

    return decorator
