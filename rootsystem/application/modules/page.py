from __future__ import annotations

import sys
from starlette.requests import Request
from core.jinja import templates
from settings import DB_ENGINE, DEBUG, THROTTLE_BACKEND, CACHE_BACKEND


class PageController:

    async def home(self, request: Request):
        python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

        # Lazy import to avoid circular import with routes.py
        from routes import routes
        route_count = len(routes)

        return templates.TemplateResponse(request, 'home.html', {
            'user_id': request.session.get('user_id'),
            'nori_version': '1.1.0',
            'python_version': python_version,
            'db_engine': DB_ENGINE,
            'debug_mode': DEBUG,
            'throttle_backend': THROTTLE_BACKEND,
            'cache_backend': CACHE_BACKEND,
            'route_count': route_count,
        })
