"""
Audit logging utility.

Fire-and-forget: ``audit()`` schedules the database write immediately
via ``asyncio`` — no need to capture the return value or attach it to
a response.

Usage::

    from core.audit import audit

    async def create(self, request):
        article = await Article.create(...)
        audit(request, 'create', model_name='Article', record_id=article.id)
        return JSONResponse({'ok': True})
"""
from __future__ import annotations

import asyncio
from typing import Any

from starlette.requests import Request

from core.conf import config
from core.logger import get_logger
from core.registry import get_model

_log = get_logger('audit')

__all__ = ['audit', 'get_client_ip']


def get_client_ip(request: Request) -> str | None:
    """Extract the client IP, respecting X-Forwarded-For only from trusted proxies.

    Set ``TRUSTED_PROXIES`` in ``.env`` (comma-separated IPs) to trust
    ``X-Forwarded-For`` headers from those addresses.  When the direct
    client IP is not in the trusted list, ``X-Forwarded-For`` is ignored
    to prevent IP spoofing.
    """
    direct_ip = request.client.host if request.client else None
    trusted = config.get('TRUSTED_PROXIES', [])

    if trusted and direct_ip in trusted:
        forwarded = request.headers.get('x-forwarded-for')
        if forwarded:
            ip = forwarded.split(',')[0].strip()
            if ip:
                return ip

    return direct_ip


def audit(
    request: Request,
    action: str,
    *,
    model_name: str | None = None,
    record_id: Any = None,
    changes: dict[str, Any] | None = None,
    user_id: int | None = None,
) -> asyncio.Task | None:
    """Write an audit log entry as a fire-and-forget async task.

    The database write is scheduled immediately via ``asyncio`` — there
    is no need to attach it to a response.  The returned
    ``asyncio.Task`` can be awaited in tests or ignored in production.

    ``user_id`` is resolved from ``request.session['user_id']`` when not
    provided explicitly.
    """
    raw_uid = user_id if user_id is not None else request.session.get('user_id')
    resolved_user_id = int(raw_uid) if raw_uid is not None else None
    ip = get_client_ip(request)
    request_id = getattr(request.state, 'request_id', None)

    _log.info(
        "action=%s user=%s model=%s record=%s ip=%s request_id=%s",
        action, resolved_user_id, model_name, record_id, ip, request_id,
    )

    async def _write() -> None:
        try:
            _AuditLog = get_model('AuditLog')
            await _AuditLog.create(
                user_id=resolved_user_id,
                action=action,
                model_name=model_name,
                record_id=str(record_id) if record_id is not None else None,
                changes=changes,
                ip_address=ip,
                request_id=request_id,
            )
        except Exception:
            _log.exception("Failed to write audit log entry")

    try:
        loop = asyncio.get_running_loop()
        return loop.create_task(_write())
    except RuntimeError:
        _log.warning("No running event loop — audit entry for '%s' was not persisted", action)
        return None
