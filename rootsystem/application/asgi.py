from __future__ import annotations

"""
Nori - ASGI Entry Point
Start with: uvicorn asgi:app --reload --host 0.0.0.0 --port 8000
"""
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.staticfiles import StaticFiles
from tortoise import Tortoise

import settings
from routes import routes
from core.auth.csrf import CsrfMiddleware
from core.http.request_id import RequestIdMiddleware
from core.http.security_headers import SecurityHeadersMiddleware
from core.jinja import templates
from core.logger import get_logger

_log = get_logger('asgi')

# Lifecycle

@asynccontextmanager
async def lifespan(app):
    # Validate settings on startup
    warnings = settings.validate_settings()
    for w in warnings:
        _log.warning("Settings: %s", w)

    if settings.DB_ENABLED:
        await Tortoise.init(config=settings.TORTOISE_ORM)
        if settings.DEBUG:
            await Tortoise.generate_schemas()
        _log.info("Nori started [debug=%s, db=%s]", settings.DEBUG, settings.DB_ENGINE)
    else:
        _log.info("Nori started [debug=%s, db=disabled]", settings.DEBUG)
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

# Middleware stack (order: RequestId -> SecurityHeaders -> CORS -> Session -> CSRF)

middleware = [
    Middleware(RequestIdMiddleware),
    Middleware(SecurityHeadersMiddleware),
    Middleware(SessionMiddleware, secret_key=settings.SECRET_KEY, https_only=not settings.DEBUG),
    Middleware(CsrfMiddleware),
]

if settings.CORS_ORIGINS:
    middleware.insert(1, Middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_methods=settings.CORS_ALLOW_METHODS,
        allow_headers=settings.CORS_ALLOW_HEADERS,
        allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    ))

# Application

app = Starlette(
    debug=settings.DEBUG,
    routes=routes,
    middleware=middleware,
    exception_handlers=exception_handlers,
    lifespan=lifespan,
)

app.mount('/static', StaticFiles(directory=settings.STATIC_DIR), name='static')
