"""Tests for services/mail_resend.py — Resend mail driver."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from services.mail_resend import _send_via_resend, register


@pytest.fixture(autouse=True)
def _resend_settings(monkeypatch):
    """Ensure MAIL_FROM and RESEND_API_KEY exist on settings."""
    import settings

    monkeypatch.setattr(settings, 'MAIL_FROM', 'nori@test.com', raising=False)
    monkeypatch.setattr(settings, 'RESEND_API_KEY', 'test-key-123', raising=False)


# ---------------------------------------------------------------------------
# register()
# ---------------------------------------------------------------------------


def test_register_adds_resend_driver():
    with patch('services.mail_resend.register_mail_driver') as mock_reg:
        register()
    mock_reg.assert_called_once_with('resend', _send_via_resend)


# ---------------------------------------------------------------------------
# _send_via_resend()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_via_resend_basic():

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch('services.mail_resend.httpx.AsyncClient', return_value=mock_client):
        await _send_via_resend(
            to=['user@example.com'],
            subject='Hello',
            body_html='<p>Hi</p>',
        )

    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args
    assert call_kwargs[0][0] == 'https://api.resend.com/emails'
    assert call_kwargs[1]['headers']['Authorization'] == 'Bearer test-key-123'
    payload = call_kwargs[1]['json']
    assert payload['from'] == 'nori@test.com'
    assert payload['to'] == ['user@example.com']
    assert payload['subject'] == 'Hello'
    assert payload['html'] == '<p>Hi</p>'
    assert 'text' not in payload


@pytest.mark.asyncio
async def test_send_via_resend_with_text_body():
    """Includes plain-text body when provided."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch('services.mail_resend.httpx.AsyncClient', return_value=mock_client):
        await _send_via_resend(
            to=['user@example.com'],
            subject='Hello',
            body_html='<p>Hi</p>',
            body_text='Hi plain',
        )

    payload = mock_client.post.call_args[1]['json']
    assert payload['text'] == 'Hi plain'


@pytest.mark.asyncio
async def test_send_via_resend_raises_on_http_error():
    """Propagates httpx.HTTPStatusError on API failure."""
    import httpx

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError('error', request=MagicMock(), response=MagicMock())
    )

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch('services.mail_resend.httpx.AsyncClient', return_value=mock_client):
        with pytest.raises(httpx.HTTPStatusError):
            await _send_via_resend(
                to=['user@example.com'],
                subject='Fail',
                body_html='<p>Fail</p>',
            )
