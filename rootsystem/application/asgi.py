"""
Nori - ASGI Entry Point
Start with: uvicorn asgi:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

# Bootstrap hook — MUST run before any framework/third-party import so
# observability SDKs (Sentry, OTel, Datadog) can patch libraries at load time.
from core.bootstrap import load_bootstrap

load_bootstrap()

from contextlib import asynccontextmanager

import settings
from core.conf import configure
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.staticfiles import StaticFiles
from tortoise import Tortoise

configure(settings)
from core.auth.csrf import CsrfMiddleware
from core.http.request_id import RequestIdMiddleware
from core.http.security_headers import SecurityHeadersMiddleware
from core.jinja import templates
from core.logger import get_logger
from routes import routes

_log = get_logger('asgi')

# Lifecycle


@asynccontextmanager
async def lifespan(app):
    # Validate settings on startup
    warnings = settings.validate_settings()
    for w in warnings:
        _log.warning('Settings: %s', w)

    # Warn about memory backends in production
    if not settings.DEBUG:
        if getattr(settings, 'CACHE_BACKEND', 'memory') == 'memory':
            _log.warning(
                "CACHE_BACKEND is 'memory' in production. Cache is not shared across "
                'workers and will be lost on restart. Set CACHE_BACKEND=redis.'
            )
        if getattr(settings, 'THROTTLE_BACKEND', 'memory') == 'memory':
            _log.warning(
                "THROTTLE_BACKEND is 'memory' in production. Rate limits are not shared "
                'across workers. Set THROTTLE_BACKEND=redis.'
            )

    # Fail-fast: verify network-backed backends are reachable. RuntimeError
    # here aborts startup so misconfigured deployments don't silently serve
    # requests against a broken cache/throttle.
    from core.cache import get_backend as _get_cache_backend
    from core.http.throttle_backends import get_backend as _get_throttle_backend

    await _get_cache_backend().verify()
    await _get_throttle_backend().verify()

    if settings.DB_ENABLED:
        await Tortoise.init(config=settings.TORTOISE_ORM)
        if settings.DEBUG:
            await Tortoise.generate_schemas()
        _log.info('Nori started [debug=%s, db=%s]', settings.DEBUG, settings.DB_ENGINE)
    else:
        _log.info('Nori started [debug=%s, db=disabled]', settings.DEBUG)
    yield
    if settings.DB_ENABLED:
        await Tortoise.close_connections()


# Error handler


async def not_found(request: Request, exc: Exception) -> Response:
    accept = request.headers.get('accept', '')
    if 'application/json' in accept:
        return JSONResponse({'error': 'Not Found'}, status_code=404)
    return templates.TemplateResponse(request, '404.html', status_code=404)


async def server_error(request: Request, exc: Exception) -> Response:
    _log.error('Internal server error on %s: %s', request.url.path, exc, exc_info=True)
    return templates.TemplateResponse(request, '500.html', status_code=500)


exception_handlers = {} if settings.DEBUG else {404: not_found, 500: server_error}

# Middleware stack — order matters. Starlette wraps middleware in list order,
# so the first entry is the outermost (runs first on request, last on response).
# Order: RequestId -> SecurityHeaders -> CORS (if enabled) -> Session -> CSRF.
# SecurityHeaders MUST wrap CORS so preflight responses receive security headers.


def _build_middleware(settings_module) -> list[Middleware]:
    stack = [
        Middleware(RequestIdMiddleware),
        Middleware(SecurityHeadersMiddleware),
        Middleware(
            SessionMiddleware,
            secret_key=settings_module.SECRET_KEY,
            https_only=not settings_module.DEBUG,
        ),
        Middleware(CsrfMiddleware),
    ]
    if settings_module.CORS_ORIGINS:
        stack.insert(
            2,
            Middleware(
                CORSMiddleware,
                allow_origins=settings_module.CORS_ORIGINS,
                allow_methods=settings_module.CORS_ALLOW_METHODS,
                allow_headers=settings_module.CORS_ALLOW_HEADERS,
                allow_credentials=settings_module.CORS_ALLOW_CREDENTIALS,
            ),
        )
    return stack


middleware = _build_middleware(settings)

# Application

app = Starlette(
    debug=settings.DEBUG,
    routes=routes,
    middleware=middleware,
    exception_handlers=exception_handlers,
    lifespan=lifespan,
)

app.mount('/static', StaticFiles(directory=settings.STATIC_DIR), name='static')
