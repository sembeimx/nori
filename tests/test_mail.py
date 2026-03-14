"""Tests for core.mail — message builder and multi-driver dispatcher.

Covers:
- MIME message construction (_build_message)
- Recipient normalization (_normalize_recipients)
- Driver dispatch (smtp, log, custom, unknown)
- Template rendering before dispatch
- Validation (missing body)
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../rootsystem/application')))

import pytest
from unittest.mock import AsyncMock, patch

import core.mail as mail_module
from core.mail import (
    _build_message,
    _normalize_recipients,
    _send_via_log,
    _send_via_smtp,
    send_mail,
    register_mail_driver,
    get_mail_drivers,
    _DRIVERS,
)


@pytest.fixture(autouse=True)
def _cleanup_drivers():
    """Remove any test drivers registered during a test."""
    yield
    _DRIVERS.pop('test_custom', None)


# ---------------------------------------------------------------------------
# _build_message
# ---------------------------------------------------------------------------

def test_build_message_html_only():
    """HTML-only message has correct headers and a single text/html part."""
    msg = _build_message('user@test.com', 'Hello', '<h1>Hi</h1>')
    assert msg['Subject'] == 'Hello'
    assert msg['To'] == 'user@test.com'
    parts = msg.get_payload()
    assert len(parts) == 1
    assert parts[0].get_content_type() == 'text/html'


def test_build_message_with_text_fallback():
    """Message with text fallback contains both text/plain and text/html."""
    msg = _build_message('user@test.com', 'Hello', '<h1>Hi</h1>', body_text='Hi')
    parts = msg.get_payload()
    assert len(parts) == 2
    assert parts[0].get_content_type() == 'text/plain'
    assert parts[1].get_content_type() == 'text/html'


def test_build_message_multiple_recipients():
    """Multiple recipients are joined with comma in the To header."""
    msg = _build_message(['a@test.com', 'b@test.com'], 'Hello', '<p>Hi</p>')
    assert msg['To'] == 'a@test.com, b@test.com'


def test_build_message_mime_structure():
    """Message uses multipart/alternative MIME type."""
    msg = _build_message('user@test.com', 'Test', '<p>test</p>')
    assert msg.get_content_type() == 'multipart/alternative'


# ---------------------------------------------------------------------------
# _normalize_recipients
# ---------------------------------------------------------------------------

def test_normalize_recipients_str():
    """A single string address is wrapped in a list."""
    assert _normalize_recipients('a@b.com') == ['a@b.com']


def test_normalize_recipients_list():
    """A list of addresses is returned as-is."""
    result = _normalize_recipients(['a@b.com', 'c@d.com'])
    assert result == ['a@b.com', 'c@d.com']


# ---------------------------------------------------------------------------
# send_mail — dispatch
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_send_mail_dispatches_to_smtp():
    """Default driver dispatches to the smtp handler."""
    mock_smtp = AsyncMock()
    with patch.dict(_DRIVERS, {'smtp': mock_smtp}), \
         patch.object(mail_module, 'settings') as mock_settings:
        mock_settings.MAIL_DRIVER = 'smtp'
        await send_mail(to='a@b.com', subject='Hi', body_html='<p>hi</p>')
        mock_smtp.assert_called_once_with(['a@b.com'], 'Hi', '<p>hi</p>', None)


@pytest.mark.anyio
async def test_send_mail_driver_override():
    """Per-call driver= overrides settings.MAIL_DRIVER."""
    mock_log = AsyncMock()
    with patch.dict(_DRIVERS, {'log': mock_log}), \
         patch.object(mail_module, 'settings') as mock_settings:
        mock_settings.MAIL_DRIVER = 'smtp'
        await send_mail(to='a@b.com', subject='Hi', body_html='<p>hi</p>', driver='log')
        mock_log.assert_called_once()


@pytest.mark.anyio
async def test_send_mail_unknown_driver():
    """Unknown driver raises ValueError with the driver name."""
    with pytest.raises(ValueError, match="Unknown mail driver 'nonexistent'"):
        await send_mail(to='a@b.com', subject='Hi', body_html='<p>hi</p>', driver='nonexistent')


@pytest.mark.anyio
async def test_send_mail_missing_body_and_template():
    """Calling send_mail without body_html or template raises ValueError."""
    with pytest.raises(ValueError, match="Either body_html or template is required"):
        await send_mail(to='a@b.com', subject='Hi')


# ---------------------------------------------------------------------------
# register_mail_driver
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_register_mail_driver():
    """A custom driver can be registered and dispatched to."""
    custom = AsyncMock()
    register_mail_driver('test_custom', custom)

    await send_mail(to='x@y.com', subject='S', body_html='<b>b</b>', driver='test_custom')
    custom.assert_called_once_with(['x@y.com'], 'S', '<b>b</b>', None)


# ---------------------------------------------------------------------------
# get_mail_drivers
# ---------------------------------------------------------------------------

def test_get_mail_drivers():
    """Built-in drivers smtp and log are always present."""
    drivers = get_mail_drivers()
    assert 'smtp' in drivers
    assert 'log' in drivers


# ---------------------------------------------------------------------------
# _send_via_log
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_send_via_log():
    """Log driver completes without raising."""
    await _send_via_log(['a@b.com'], 'Test', '<p>test</p>')


# ---------------------------------------------------------------------------
# _send_via_smtp
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_send_via_smtp():
    """SMTP driver passes a MIMEMultipart message to aiosmtplib.send."""
    with patch('core.mail.aiosmtplib.send', new_callable=AsyncMock) as mock_send:
        await _send_via_smtp(['user@test.com'], 'Hello', '<p>Hi</p>')
        mock_send.assert_called_once()
        msg = mock_send.call_args[0][0]
        assert msg.get_content_type() == 'multipart/alternative'
        assert msg['To'] == 'user@test.com'


# ---------------------------------------------------------------------------
# send_mail — template rendering
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_send_mail_renders_template():
    """Template is rendered to HTML before dispatching to the driver."""
    mock_smtp = AsyncMock()
    with patch.object(mail_module, '_render_template', return_value='<p>rendered</p>') as mock_render, \
         patch.dict(_DRIVERS, {'smtp': mock_smtp}), \
         patch.object(mail_module, 'settings') as mock_settings:
        mock_settings.MAIL_DRIVER = 'smtp'
        await send_mail(to='a@b.com', subject='S', template='email/test.html', context={'k': 'v'})
        mock_render.assert_called_once_with('email/test.html', {'k': 'v'})
        mock_smtp.assert_called_once_with(['a@b.com'], 'S', '<p>rendered</p>', None)
