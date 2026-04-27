"""Route auth decorators: login_required, require_role, require_permission, token_required."""

from __future__ import annotations

import time
from collections.abc import Callable
from functools import wraps
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from core.auth.jwt import verify_token as _verify_token
from core.conf import config
from core.registry import get_model

_PERMISSIONS_TTL_KEY = '_permissions_loaded_at'
_DEFAULT_PERMISSIONS_TTL = 300  # 5 minutes


def login_required(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator: redirects to /login if no session.
    For JSON requests, returns 401.
    """

    @wraps(func)
    async def wrapper(self: Any, request: Request, *args: Any, **kwargs: Any) -> Response:
        user_id = request.session.get('user_id')
        if not user_id:
            accept = request.headers.get('accept', '')
            if 'application/json' in accept:
                return JSONResponse({'error': 'Unauthorized'}, status_code=401)
            return RedirectResponse(config.get('LOGIN_URL', '/login'), status_code=302)
        return await func(self, request, *args, **kwargs)

    return wrapper


def require_role(role: str) -> Callable[..., Any]:
    """
    Decorator: requires a specific role. Admin bypasses all roles.

        @require_role('editor')
        async def edit(self, request): ...
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(self: Any, request: Request, *args: Any, **kwargs: Any) -> Response:
            user_id = request.session.get('user_id')
            if not user_id:
                accept = request.headers.get('accept', '')
                if 'application/json' in accept:
                    return JSONResponse({'error': 'Unauthorized'}, status_code=401)
                return RedirectResponse(config.get('LOGIN_URL', '/login'), status_code=302)

            user_role = request.session.get('role', 'user')
            if user_role != 'admin' and user_role != role:
                accept = request.headers.get('accept', '')
                if 'application/json' in accept:
                    return JSONResponse({'error': 'Forbidden'}, status_code=403)
                return RedirectResponse(config.get('FORBIDDEN_URL', '/forbidden'), status_code=302)

            return await func(self, request, *args, **kwargs)

        return wrapper

    return decorator


def require_any_role(*roles: str) -> Callable[..., Any]:
    """
    Decorator: requires one of the specified roles.

        @require_any_role('admin', 'moderator')
        async def moderate(self, request): ...
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(self: Any, request: Request, *args: Any, **kwargs: Any) -> Response:
            user_id = request.session.get('user_id')
            if not user_id:
                accept = request.headers.get('accept', '')
                if 'application/json' in accept:
                    return JSONResponse({'error': 'Unauthorized'}, status_code=401)
                return RedirectResponse(config.get('LOGIN_URL', '/login'), status_code=302)

            user_role = request.session.get('role', 'user')
            if user_role != 'admin' and user_role not in roles:
                accept = request.headers.get('accept', '')
                if 'application/json' in accept:
                    return JSONResponse({'error': 'Forbidden'}, status_code=403)
                return RedirectResponse(config.get('FORBIDDEN_URL', '/forbidden'), status_code=302)

            return await func(self, request, *args, **kwargs)

        return wrapper

    return decorator


async def load_permissions(session: dict, user_id: int) -> list[str]:
    """Query Role→Permission M2M and cache permission names in the session.

    Call this at login time after setting ``session['role_ids']``::

        await load_permissions(request.session, user.id)

    If ``role_ids`` is missing or empty the session will have an empty
    permissions list and a warning is logged.
    """
    from core.logger import get_logger

    _perm_log = get_logger('auth')

    Role = get_model('Role')
    role_ids = session.get('role_ids', [])
    if not role_ids:
        _perm_log.warning('load_permissions called but role_ids is empty for user %s', user_id)
        session['permissions'] = []
        return []

    roles = await Role.filter(
        id__in=role_ids,
    ).prefetch_related('permissions')
    perms: list[str] = []
    for role in roles:
        for perm in role.permissions:
            if perm.name not in perms:
                perms.append(perm.name)
    session['permissions'] = perms
    session[_PERMISSIONS_TTL_KEY] = time.time()
    return perms


def require_permission(perm: str) -> Callable[..., Any]:
    """
    Decorator: requires a specific permission. Admin bypasses.

    Permissions are auto-refreshed from the database when the session
    cache expires (default: 5 minutes, configurable via
    ``PERMISSIONS_TTL`` in settings).

        @require_permission('articles.edit')
        async def edit(self, request): ...
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(self: Any, request: Request, *args: Any, **kwargs: Any) -> Response:
            user_id = request.session.get('user_id')
            if not user_id:
                accept = request.headers.get('accept', '')
                if 'application/json' in accept:
                    return JSONResponse({'error': 'Unauthorized'}, status_code=401)
                return RedirectResponse(config.get('LOGIN_URL', '/login'), status_code=302)

            user_role = request.session.get('role', 'user')
            if user_role == 'admin':
                return await func(self, request, *args, **kwargs)

            # Auto-refresh permissions if TTL expired (only if loaded via load_permissions before)
            loaded_at = request.session.get(_PERMISSIONS_TTL_KEY)
            if loaded_at is not None:
                ttl = int(config.get('PERMISSIONS_TTL', _DEFAULT_PERMISSIONS_TTL))
                if time.time() - loaded_at > ttl:
                    await load_permissions(request.session, int(user_id))

            permissions = request.session.get('permissions', [])
            if perm not in permissions:
                accept = request.headers.get('accept', '')
                if 'application/json' in accept:
                    return JSONResponse({'error': 'Forbidden'}, status_code=403)
                return RedirectResponse(config.get('FORBIDDEN_URL', '/forbidden'), status_code=302)

            return await func(self, request, *args, **kwargs)

        return wrapper

    return decorator


def token_required(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator: requires a valid JWT Bearer token.
    Extracts token from Authorization header, verifies it,
    and stores payload in request.state.token_payload.

        @token_required
        async def api_data(self, request): ...
    """

    @wraps(func)
    async def wrapper(self: Any, request: Request, *args: Any, **kwargs: Any) -> Response:
        auth_header = request.headers.get('authorization', '').strip()
        if not auth_header.lower().startswith('bearer '):
            return JSONResponse({'error': 'Unauthorized'}, status_code=401)

        token = auth_header[7:].strip()
        if not token or len(token) > 4096:
            return JSONResponse({'error': 'Unauthorized'}, status_code=401)
        payload = _verify_token(token)
        if payload is None:
            return JSONResponse({'error': 'Unauthorized'}, status_code=401)

        request.state.token_payload = payload
        return await func(self, request, *args, **kwargs)

    return wrapper
