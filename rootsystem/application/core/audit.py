"""
Audit logging utility.

Usage::

    from core.audit import audit

    async def create(self, request):
        article = await Article.create(...)
        task = audit(request, 'create', model_name='Article', record_id=article.id)
        return JSONResponse({'ok': True}, background=task)
"""
from __future__ import annotations

from typing import Any

from starlette.background import BackgroundTask
from starlette.requests import Request

from core.logger import get_logger
from core.tasks import background

_log = get_logger('audit')

__all__ = ['audit', 'get_client_ip']


def get_client_ip(request: Request) -> str | None:
    """Extract the client IP, respecting X-Forwarded-For behind a proxy."""
    forwarded = request.headers.get('x-forwarded-for')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.client.host if request.client else None


def audit(
    request: Request,
    action: str,
    *,
    model_name: str | None = None,
    record_id: Any = None,
    changes: dict[str, Any] | None = None,
    user_id: int | None = None,
) -> BackgroundTask:
    """Create a BackgroundTask that writes an audit log entry.

    Returns a ``BackgroundTask`` suitable for passing to a response's
    ``background=`` parameter.

    ``user_id`` is resolved from ``request.session['user_id']`` when not
    provided explicitly.
    """
    resolved_user_id = user_id if user_id is not None else request.session.get('user_id')
    ip = get_client_ip(request)
    request_id = getattr(request.state, 'request_id', None)

    _log.info(
        "action=%s user=%s model=%s record=%s ip=%s request_id=%s",
        action, resolved_user_id, model_name, record_id, ip, request_id,
    )

    async def _write() -> None:
        from models.audit_log import AuditLog
        await AuditLog.create(
            user_id=resolved_user_id,
            action=action,
            model_name=model_name,
            record_id=str(record_id) if record_id is not None else None,
            changes=changes,
            ip_address=ip,
            request_id=request_id,
        )

    return background(_write)
