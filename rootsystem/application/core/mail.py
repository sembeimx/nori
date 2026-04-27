"""
Multi-driver email dispatcher.

    from core.mail import send_mail

    await send_mail(
        to='user@example.com',
        subject='Welcome',
        body_html='<h1>Hello!</h1>',
    )

    # Or with template:
    await send_mail(
        to='user@example.com',
        subject='Welcome',
        template='email/welcome.html',
        context={'name': 'Alice'},
    )

    # Override driver per-call:
    await send_mail(to='...', subject='...', body_html='...', driver='log')

    # Register a custom driver:
    from core.mail import register_mail_driver

    async def my_driver(to, subject, body_html, body_text):
        ...

    register_mail_driver('custom', my_driver)
"""

from __future__ import annotations

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Callable

import aiosmtplib

from core.conf import config
from core.jinja import templates
from core.logger import get_logger


def _build_message(
    to: str | list[str],
    subject: str,
    body_html: str,
    body_text: str | None = None,
) -> MIMEMultipart:
    """Build a MIME multipart email message."""
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = config.get('MAIL_FROM', '')
    msg['To'] = to if isinstance(to, str) else ', '.join(to)

    if body_text:
        msg.attach(MIMEText(body_text, 'plain', 'utf-8'))

    msg.attach(MIMEText(body_html, 'html', 'utf-8'))

    return msg


def _render_template(template: str, context: dict | None = None) -> str:
    """Render a Jinja2 template for email."""
    tmpl = templates.env.get_template(template)
    return tmpl.render(context or {})


def _normalize_recipients(to: str | list[str]) -> list[str]:
    """Normalize recipient(s) into a list of strings.

    Args:
        to: A single email address string or a list of addresses.

    Returns:
        A list of email address strings. If ``to`` is already a list,
        a shallow copy is returned.

    Examples::

        >>> _normalize_recipients('a@b.com')
        ['a@b.com']
        >>> _normalize_recipients(['a@b.com', 'c@d.com'])
        ['a@b.com', 'c@d.com']
    """
    if isinstance(to, str):
        return [to]
    return list(to)


async def _send_via_smtp(
    to: list[str],
    subject: str,
    body_html: str,
    body_text: str | None = None,
) -> None:
    """Send email via SMTP using aiosmtplib.

    Reads connection settings (host, port, user, password, TLS) from
    ``settings``. This is the default mail driver.

    Args:
        to: List of recipient email addresses.
        subject: Email subject line.
        body_html: HTML body content.
        body_text: Optional plain-text fallback body.
    """
    msg = _build_message(to, subject, body_html, body_text)

    mail_host = config.get('MAIL_HOST', 'localhost')
    mail_port = config.get('MAIL_PORT', 587)
    mail_user = config.get('MAIL_USER', '')
    mail_password = config.get('MAIL_PASSWORD', '')
    mail_tls = config.get('MAIL_TLS', True)

    await aiosmtplib.send(
        msg,
        hostname=mail_host,
        port=mail_port,
        username=mail_user or None,
        password=mail_password or None,
        start_tls=mail_tls,
    )


_log = get_logger('mail')


async def _send_via_log(
    to: list[str],
    subject: str,
    body_html: str,
    body_text: str | None = None,
) -> None:
    """Log the email instead of sending it.

    Useful during development to verify that emails are being dispatched
    without actually connecting to an SMTP server. Output goes to the
    ``nori.mail`` logger at INFO level.

    Args:
        to: List of recipient email addresses.
        subject: Email subject line.
        body_html: HTML body content.
        body_text: Optional plain-text fallback body.
    """
    _log.info(
        'Mail [driver=log] to=%s subject=%r html_len=%d text=%s',
        to,
        subject,
        len(body_html),
        bool(body_text),
    )


# ---------------------------------------------------------------------------
# Driver registry
# ---------------------------------------------------------------------------

_DRIVERS: dict[str, Callable] = {
    'smtp': _send_via_smtp,
    'log': _send_via_log,
}


def register_mail_driver(name: str, handler: Callable) -> None:
    """Register a custom mail driver.

    The handler must be an async callable with signature:
        async def handler(to: list[str], subject: str, body_html: str, body_text: str | None) -> None
    """
    _DRIVERS[name] = handler


def get_mail_drivers() -> set[str]:
    """Return the names of all registered mail drivers."""
    return set(_DRIVERS)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def send_mail(
    *,
    to: str | list[str],
    subject: str,
    body_html: str | None = None,
    body_text: str | None = None,
    template: str | None = None,
    context: dict | None = None,
    driver: str | None = None,
) -> None:
    """
    Send an email using the configured (or overridden) driver.

    Args:
        to: Recipient address(es).
        subject: Email subject.
        body_html: HTML body (mutually exclusive with template).
        body_text: Optional plain text fallback.
        template: Jinja2 template path (renders to body_html).
        context: Template context dict.
        driver: Override the default driver for this call.
    """
    if template:
        body_html = _render_template(template, context)

    if not body_html:
        raise ValueError('Either body_html or template is required')

    driver_name = driver or config.get('MAIL_DRIVER', 'smtp')
    handler = _DRIVERS.get(driver_name)
    if handler is None:
        available = ', '.join(sorted(_DRIVERS))
        raise ValueError(f"Unknown mail driver '{driver_name}'. Available drivers: {available}")

    recipients = _normalize_recipients(to)
    await handler(recipients, subject, body_html, body_text)
