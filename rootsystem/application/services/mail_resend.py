"""
Resend mail driver for Nori.

Usage in your app startup or routes.py:
    from services.mail_resend import register
    register()

Then set MAIL_DRIVER=resend in your .env (or pass driver='resend' per-call).

Requires: RESEND_API_KEY and MAIL_FROM in settings/.env
"""
from __future__ import annotations

import httpx

import settings
from core.mail import register_mail_driver


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
        "from": settings.MAIL_FROM,
        "to": to,
        "subject": subject,
        "html": body_html,
    }
    if body_text:
        payload["text"] = body_text

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
            json=payload,
        )
        resp.raise_for_status()


def register():
    """Register the Resend mail driver."""
    register_mail_driver('resend', _send_via_resend)
