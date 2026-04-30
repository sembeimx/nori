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


def _superuser_role() -> str:
    """Return the role name that bypasses all auth checks.

    Defaults to ``'admin'`` for backward compatibility. Projects can
    rename it (``owner``, ``root``) or disable the bypass entirely by
    setting ``SUPERUSER_ROLE = ''`` in ``settings.py``.

    Hardcoding ``'admin'`` would also mean any bug in session handling
    or a third-party OIDC claim that lets a user set their role to
    ``admin`` grants total access — making the role name configurable
    lets projects pick a name no untrusted system can produce.
    """
    return config.get('SUPERUSER_ROLE', 'admin')


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
    Decorator: requires a specific role. The configured superuser role
    (``SUPERUSER_ROLE``, default ``'admin'``) bypasses all role checks.

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
            superuser = _superuser_role()
            if (not superuser or user_role != superuser) and user_role != role:
                accept = request.headers.get('accept', '')
                if 'application/json' in accept:
                    return JSONResponse({'error': 'Forbidden'}, status_code=403)
                return RedirectResponse(config.get('FORBIDDEN_URL', '/forbidden'), status_code=302)

            return await func(self, request, *args, **kwargs)

        return wrapper

    return decorator


def require_any_role(*roles: str) -> Callable[..., Any]:
    """
    Decorator: requires one of the specified roles. The configured
    superuser role (``SUPERUSER_ROLE``, default ``'admin'``) bypasses.

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
            superuser = _superuser_role()
            if (not superuser or user_role != superuser) and user_role not in roles:
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
    permissions list and a warning is logged. The TTL marker is set in
    every branch so :func:`require_permission`'s fail-safe load runs at
    most once per TTL window — without that, a session lacking
    ``role_ids`` would re-trigger the load on every request.
    """
    from core.logger import get_logger

    _perm_log = get_logger('auth')

    role_ids = session.get('role_ids', [])
    if not role_ids:
        _perm_log.warning('load_permissions called but role_ids is empty for user %s', user_id)
        session['permissions'] = []
        session[_PERMISSIONS_TTL_KEY] = time.time()
        return []

    Role = get_model('Role')
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
            superuser = _superuser_role()
            if superuser and user_role == superuser:
                return await func(self, request, *args, **kwargs)

            # Fail-safe permissions load. Two cases trigger a (re)load:
            #   1. TTL marker absent AND permissions list empty — the
            #      project's login flow forgot to call load_permissions
            #      and the user has nothing in session; without this
            #      branch they're locked out of every gated route.
            #   2. TTL marker present but expired — normal periodic
            #      refresh so role/permission changes propagate without
            #      forcing a re-login.
            # If permissions are populated without a TTL marker (manual
            # session writes from an OAuth callback, tests, etc.) we
            # respect them — overwriting would silently break those
            # flows.
            loaded_at = request.session.get(_PERMISSIONS_TTL_KEY)
            permissions = request.session.get('permissions', [])
            ttl = int(config.get('PERMISSIONS_TTL', _DEFAULT_PERMISSIONS_TTL))

            needs_initial_load = loaded_at is None and not permissions
            needs_refresh = loaded_at is not None and (time.time() - loaded_at > ttl)
            if needs_initial_load or needs_refresh:
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
        payload = await _verify_token(token)
        if payload is None:
            return JSONResponse({'error': 'Unauthorized'}, status_code=401)

        request.state.token_payload = payload
        return await func(self, request, *args, **kwargs)

    return wrapper
