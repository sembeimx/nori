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


def _warn_missing_trusted_proxies(settings_module, logger) -> bool:
    """Warn when ``TRUSTED_PROXIES`` is empty in a non-DEBUG deployment.

    The framework fails secure: ``get_client_ip`` ignores
    ``X-Forwarded-For`` from any source not in ``TRUSTED_PROXIES``, so
    forging a client IP is impossible by default. The cost of that
    posture is observability — behind a load balancer,
    ``request.client.host`` is always the proxy's internal address, so
    every audit log entry records ``10.0.0.1`` (or similar) instead of
    the real client. A silent observability gap is worth one loud
    startup warning so operators discover the misconfiguration before
    they need the audit trail.

    Returns ``True`` if a warning was emitted (used in tests).
    """
    if settings_module.DEBUG:
        return False
    if getattr(settings_module, 'TRUSTED_PROXIES', None):
        return False
    logger.warning(
        'TRUSTED_PROXIES is empty in production. Behind a load balancer or '
        "reverse proxy, audit logs and rate-limits will record the proxy's "
        'internal IP for every request, not the real client. Set '
        'TRUSTED_PROXIES=<proxy_ip> in your .env (comma-separated for multiple).'
    )
    return True


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
        _warn_missing_trusted_proxies(settings, _log)

    # Fail-fast: verify network-backed backends are reachable. RuntimeError
    # here aborts startup so misconfigured deployments don't silently serve
    # requests against a broken cache/throttle. We log via _log.critical so
    # JSON log pipelines (LOG_FORMAT=json) get the structured event, not
    # just a stderr traceback.
    from core.cache import get_backend as _get_cache_backend
    from core.http.throttle_backends import get_backend as _get_throttle_backend

    try:
        await _get_cache_backend().verify()
    except Exception:
        _log.critical('Startup verification of cache backend failed; aborting.', exc_info=True)
        raise
    try:
        await _get_throttle_backend().verify()
    except Exception:
        _log.critical('Startup verification of throttle backend failed; aborting.', exc_info=True)
        raise

    if settings.DB_ENABLED:
        await Tortoise.init(config=settings.TORTOISE_ORM)
        if settings.DEBUG:
            await Tortoise.generate_schemas()
        _log.info('Nori started [debug=%s, db=%s]', settings.DEBUG, settings.DB_ENGINE)
    else:
        _log.info('Nori started [debug=%s, db=disabled]', settings.DEBUG)

    # Validate session-version guard wiring AFTER models are registered
    # — get_model('User') has to find the model, and the field-presence
    # check has to see the actual schema. Loud failure if the project
    # opted into the feature but didn't add the column.
    from core.auth.session_guard import configure_session_guard

    configure_session_guard()
    yield
    # Send a clean ``close(1001)`` to every active WebSocket so connected
    # clients reconnect immediately on rolling restarts, instead of
    # waiting for uvicorn's graceful-timeout to drop the socket without
    # a frame (which clients see as ``1006`` — Abnormal Closure — and
    # treat as a transient network error with exponential backoff).
    from core.ws import close_all_connections as _close_ws

    await _close_ws()

    # Close every service-driver httpx pool that registered itself on
    # first use (S3 / GCS / OAuth / mail / search). Pre-1.27 these were
    # left to the OS to reap, which manifested as half-open sockets
    # piling up across rolling restarts and FD accumulation across
    # ``uvicorn --reload`` cycles in dev.
    from core.lifecycle import run_shutdown_handlers as _run_shutdowns

    await _run_shutdowns()

    if settings.DB_ENABLED:
        # Drain any in-flight ``audit()`` writes BEFORE the DB
        # connection pool is closed. Otherwise a SIGTERM arriving
        # immediately after a controller returns lets the audit task
        # wake up after Tortoise has already closed connections — the
        # write fails on a dead pool and the entry is lost. The flush
        # has its own short timeout so a stuck write cannot hang
        # shutdown forever.
        from core.audit import flush_pending as _flush_audit

        await _flush_audit(timeout=5.0)
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
