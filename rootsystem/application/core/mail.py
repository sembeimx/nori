"""
Email utilities with aiosmtplib.

    from core.mail import send_mail

    await send_mail(
        to='user@example.com',
        subject='Bienvenido',
        body_html='<h1>Hola!</h1>',
    )

    # Or with template:
    await send_mail(
        to='user@example.com',
        subject='Bienvenido',
        template='email/welcome.html',
        context={'name': 'Alice'},
    )
"""
from __future__ import annotations

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

import settings
from core.jinja import templates


def _build_message(
    to: str | list[str],
    subject: str,
    body_html: str,
    body_text: str | None = None,
) -> MIMEMultipart:
    """Build a MIME multipart email message."""
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = getattr(settings, 'MAIL_FROM', '')
    msg['To'] = to if isinstance(to, str) else ', '.join(to)

    if body_text:
        msg.attach(MIMEText(body_text, 'plain', 'utf-8'))

    msg.attach(MIMEText(body_html, 'html', 'utf-8'))

    return msg


def _render_template(template: str, context: dict | None = None) -> str:
    """Render a Jinja2 template for email."""
    tmpl = templates.env.get_template(template)
    return tmpl.render(context or {})


async def send_mail(
    *,
    to: str | list[str],
    subject: str,
    body_html: str | None = None,
    body_text: str | None = None,
    template: str | None = None,
    context: dict | None = None,
) -> None:
    """
    Send an email.

    Args:
        to: Recipient address(es).
        subject: Email subject.
        body_html: HTML body (mutually exclusive with template).
        body_text: Optional plain text fallback.
        template: Jinja2 template path (renders to body_html).
        context: Template context dict.
    """
    if template:
        body_html = _render_template(template, context)

    if not body_html:
        raise ValueError("Either body_html or template is required")

    msg = _build_message(to, subject, body_html, body_text)

    mail_host = getattr(settings, 'MAIL_HOST', 'localhost')
    mail_port = getattr(settings, 'MAIL_PORT', 587)
    mail_user = getattr(settings, 'MAIL_USER', '')
    mail_password = getattr(settings, 'MAIL_PASSWORD', '')
    mail_tls = getattr(settings, 'MAIL_TLS', True)

    await aiosmtplib.send(
        msg,
        hostname=mail_host,
        port=mail_port,
        username=mail_user or None,
        password=mail_password or None,
        start_tls=mail_tls,
    )
