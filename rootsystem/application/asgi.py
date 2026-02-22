"""
Nori - ASGI Entry Point
Start with: uvicorn asgi:app --reload --host 0.0.0.0 --port 8000
"""
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
from core.http.security_headers import SecurityHeadersMiddleware
from core.jinja import templates
from core.logger import get_logger

_log = get_logger('asgi')

# Lifecycle

async def on_startup():
    await Tortoise.init(config=settings.TORTOISE_ORM)

async def on_shutdown():
    await Tortoise.close_connections()

# Error handler

async def not_found(request: Request, exc: Exception) -> Response:
    accept = request.headers.get('accept', '')
    if 'application/json' in accept:
        return JSONResponse({'error': 'Not Found'}, status_code=404)
    return templates.TemplateResponse('404.html', {'request': request}, status_code=404)

async def server_error(request: Request, exc: Exception) -> Response:
    _log.error('Internal server error on %s: %s', request.url.path, exc, exc_info=True)
    return templates.TemplateResponse('500.html', {'request': request}, status_code=500)

exception_handlers = {} if settings.DEBUG else {404: not_found, 500: server_error}

# Middleware stack (orden: SecurityHeaders -> CORS -> Session -> CSRF)

middleware = [
    Middleware(SecurityHeadersMiddleware),
    Middleware(SessionMiddleware, secret_key=settings.SECRET_KEY),
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
    on_startup=[on_startup],
    on_shutdown=[on_shutdown],
)

app.mount('/static', StaticFiles(directory=settings.STATIC_DIR), name='static')
