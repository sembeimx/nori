"""
Resend mail driver for Nori.

Usage in your app startup or routes.py:
    from services.mail_resend import register
    register()

Then set MAIL_DRIVER=resend in your .env (or pass driver='resend' per-call).

Requires: RESEND_API_KEY and MAIL_FROM in settings/.env

Connection reuse:
    The driver keeps a single ``httpx.AsyncClient`` for the life of the
    process, so the TCP/TLS handshake to ``api.resend.com`` is amortized
    across all sends. Call ``await shutdown()`` from your ASGI lifespan
    to close the pool cleanly on app shutdown.
"""

from __future__ import annotations

import httpx
from core.conf import config
from core.mail import register_mail_driver

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    """Return the module-level httpx client, creating it on first use.

    A single persistent client lets httpx pool TCP/TLS connections; the
    previous per-call ``async with httpx.AsyncClient()`` paid the full
    handshake cost on every send. First call registers ``shutdown`` with
    ``core.lifecycle`` so the pool closes cleanly on graceful ASGI
    shutdown.
    """
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=30.0)
        from core.lifecycle import register_shutdown

        register_shutdown('mail_resend', shutdown)
    return _client


async def shutdown() -> None:
    """Close the shared httpx client. Call from your ASGI lifespan."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def _send_via_resend(
    to: list[str],
    subject: str,
    body_html: str,
    body_text: str | None = None,
) -> None:
    """Send an email via the Resend REST API.

    Args:
        to: List of recipient email addresses.
        subject: Email subject line.
        body_html: HTML body content.
        body_text: Optional plain-text fallback body.

    Raises:
        httpx.HTTPStatusError: If the Resend API returns a non-2xx response.
    """
    payload = {
        'from': config.MAIL_FROM,
        'to': to,
        'subject': subject,
        'html': body_html,
    }
    if body_text:
        payload['text'] = body_text

    client = _get_client()
    resp = await client.post(
        'https://api.resend.com/emails',
        headers={'Authorization': f'Bearer {config.RESEND_API_KEY}'},
        json=payload,
    )
    resp.raise_for_status()


def register():
    """Register the Resend mail driver."""
    register_mail_driver('resend', _send_via_resend)
