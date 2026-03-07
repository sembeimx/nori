from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from core.auth.jwt import verify_token as _verify_token


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
            return RedirectResponse('/login', status_code=302)
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
                return RedirectResponse('/login', status_code=302)

            user_role = request.session.get('role', 'user')
            if user_role != 'admin' and user_role != role:
                accept = request.headers.get('accept', '')
                if 'application/json' in accept:
                    return JSONResponse({'error': 'Forbidden'}, status_code=403)
                return RedirectResponse('/forbidden', status_code=302)

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
                return RedirectResponse('/login', status_code=302)

            user_role = request.session.get('role', 'user')
            if user_role != 'admin' and user_role not in roles:
                accept = request.headers.get('accept', '')
                if 'application/json' in accept:
                    return JSONResponse({'error': 'Forbidden'}, status_code=403)
                return RedirectResponse('/forbidden', status_code=302)

            return await func(self, request, *args, **kwargs)
        return wrapper
    return decorator


async def load_permissions(session: dict, user_id: int) -> list[str]:
    """Query Role→Permission M2M and cache permission names in the session.

    Call this at login time::

        await load_permissions(request.session, user.id)
    """
    from models.role import Role
    roles = await Role.filter(
        id__in=session.get('role_ids', [])
    ).prefetch_related('permissions')
    perms: list[str] = []
    for role in roles:
        for perm in role.permissions:
            if perm.name not in perms:
                perms.append(perm.name)
    session['permissions'] = perms
    return perms


def require_permission(perm: str) -> Callable[..., Any]:
    """
    Decorator: requires a specific permission. Admin bypasses.

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
                return RedirectResponse('/login', status_code=302)

            user_role = request.session.get('role', 'user')
            if user_role == 'admin':
                return await func(self, request, *args, **kwargs)

            permissions = request.session.get('permissions', [])
            if perm not in permissions:
                accept = request.headers.get('accept', '')
                if 'application/json' in accept:
                    return JSONResponse({'error': 'Forbidden'}, status_code=403)
                return RedirectResponse('/forbidden', status_code=302)

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
        auth_header = request.headers.get('authorization', '')
        if not auth_header[:7].lower() == 'bearer ':
            return JSONResponse({'error': 'Unauthorized'}, status_code=401)

        token = auth_header[7:]
        payload = _verify_token(token)
        if payload is None:
            return JSONResponse({'error': 'Unauthorized'}, status_code=401)

        request.state.token_payload = payload
        return await func(self, request, *args, **kwargs)
    return wrapper
