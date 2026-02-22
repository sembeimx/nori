from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from core.auth.jwt import verify_token as _verify_token


def login_required(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator: redirige a /login si no hay sesion.
    Para JSON requests, retorna 401.
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
    Decorator: requiere rol especifico. Admin accede a todo.

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
    Decorator: requiere uno de los roles especificados.

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
        if not auth_header.startswith('Bearer '):
            return JSONResponse({'error': 'Unauthorized'}, status_code=401)

        token = auth_header[7:]
        payload = _verify_token(token)
        if payload is None:
            return JSONResponse({'error': 'Unauthorized'}, status_code=401)

        request.state.token_payload = payload
        return await func(self, request, *args, **kwargs)
    return wrapper
