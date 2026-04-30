"""Route auth decorators: login_required, require_role, require_permission, token_required."""

from __future__ import annotations

import time
from collections.abc import Callable
from functools import wraps
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from core.auth.jwt import verify_token as _verify_token
from core.auth.session_guard import check_session_version
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


def _session_revoked_response(request: Request) -> Response:
    """Shared 401 / redirect when the session-version guard denies access.

    Same shape as the no-user-id path so the user sees a consistent
    "log in again" experience regardless of which check triggered.
    """
    accept = request.headers.get('accept', '')
    if 'application/json' in accept:
        return JSONResponse({'error': 'Session revoked'}, status_code=401)
    return RedirectResponse(config.get('LOGIN_URL', '/login'), status_code=302)


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
        if not await check_session_version(request):
            return _session_revoked_response(request)
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

            if not await check_session_version(request):
                return _session_revoked_response(request)

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

            if not await check_session_version(request):
                return _session_revoked_response(request)

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

    If ``role_ids`` is missing from the session and ``ROLE_RESOLVER`` is
    configured in ``settings.py``, the resolver is invoked to derive
    role IDs from the project's User model — this is the recommended
    pattern, since Nori has no built-in User model and cannot navigate
    a project-specific User→Role relationship on its own.

    Example resolver in ``settings.py``::

        async def _resolve_user_roles(user_id: int) -> list[int]:
            user = await User.get(id=user_id).prefetch_related('roles')
            return [r.id for r in user.roles]

        ROLE_RESOLVER = _resolve_user_roles

    Without a resolver and without ``role_ids`` in session, the function
    logs a warning and writes an empty permissions list. The TTL marker
    is set in every branch so :func:`require_permission`'s fail-safe
    load runs at most once per TTL window.
    """
    from core.logger import get_logger

    _perm_log = get_logger('auth')

    # Active-user gate. If the project registered a ``User`` model and
    # exposes an ``is_active`` flag, refuse to issue permissions for an
    # inactive (or missing) user — that closes the *refresh* path that
    # previously kept a freshly-deactivated user authorized for the
    # remainder of the ``PERMISSIONS_TTL`` window after their
    # ``is_active`` was flipped in the database.
    #
    # Within the TTL itself, the cached permissions on the session are
    # still served — there is no shared state between processes that
    # the framework can punch through here. Truly revoking access for
    # a logged-in user requires invalidating their session
    # (``session.clear()`` from an admin tool, or a cross-process
    # session blacklist); that is project-specific tooling and out of
    # scope for this gate.
    #
    # Guarded broadly: the project may not have a ``User`` model
    # (token-only auth), and an existing ``User`` may not declare
    # ``is_active`` (small internal apps without a deactivation flow).
    # Both are valid project shapes — fall through to the normal load.
    try:
        User = get_model('User')
        user_obj = await User.get_or_none(id=user_id)
        if user_obj is None or getattr(user_obj, 'is_active', True) is False:
            _perm_log.info(
                'load_permissions: refusing permissions for user %s (missing or inactive)',
                user_id,
            )
            session['permissions'] = []
            session[_PERMISSIONS_TTL_KEY] = time.time()
            return []
    except LookupError:
        # No ``User`` model registered — token-only auth or custom
        # user shape. Skip the gate.
        pass
    except Exception as exc:  # noqa: BLE001 — shape-dependent; never crash the request
        # Project-shape variations (custom Manager, no ``get_or_none``,
        # transient DB errors, AttributeError on a stub User class in
        # tests) must NOT take down the request at the gate. Log it and
        # fall through to the normal load — the convention path below
        # has its own error handling and will land at empty perms if it
        # also fails. Failing **closed** here would block every gated
        # route in projects whose User model deviates from the M2M
        # convention; the gate is a best-effort revocation channel, not
        # the primary auth boundary.
        _perm_log.warning(
            'Active-user gate query failed for user %s: %s — falling through to normal load',
            user_id,
            exc,
        )

    role_ids = session.get('role_ids', [])

    if not role_ids:
        # First fallback: project-supplied resolver derives role_ids from
        # the User model. This is what unblocks the lockout case when a
        # login flow forgets to populate role_ids — instead of a
        # permanent empty-perms state, the framework asks the project
        # how to find the user's roles.
        resolver = config.get('ROLE_RESOLVER', None)
        if callable(resolver):
            try:
                resolved = await resolver(user_id)
                if resolved:
                    role_ids = list(resolved)
                    session['role_ids'] = role_ids
            except Exception as exc:  # noqa: BLE001 — resolver is project code; never crash the request
                _perm_log.error('ROLE_RESOLVER failed for user %s: %s', user_id, exc, exc_info=True)

    if not role_ids:
        # Second fallback: zero-config convention. Many Nori projects
        # register a ``User`` model with a ``roles`` M2M to
        # ``framework.Role``; if so, derive ``role_ids`` from there
        # without forcing the project to wire up ``ROLE_RESOLVER``.
        # Wrapped broadly because every step is project-shape-dependent
        # — User may not be registered, may not have ``.roles``, the
        # row may not exist, or the relation may have a different name.
        # Any of those is a valid project shape, not an error; we fall
        # through to the warning so it stays visible.
        try:
            User = get_model('User')
            user = await User.get(id=user_id).prefetch_related('roles')
            roles_rel = getattr(user, 'roles', None)
            if roles_rel is not None:
                resolved = [r.id for r in roles_rel]
                if resolved:
                    role_ids = list(resolved)
                    session['role_ids'] = role_ids
        except LookupError:
            # User model not registered. Expected for token-only auth
            # or projects that haven't set up a User; do not log.
            pass
        except Exception as exc:  # noqa: BLE001 — shape-dependent; never crash the request
            _perm_log.warning(
                'Auto-resolve via get_model("User").roles failed for user %s: %s',
                user_id,
                exc,
            )

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

            if not await check_session_version(request):
                return _session_revoked_response(request)

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
