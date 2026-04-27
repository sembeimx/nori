"""Tests for services/storage_s3.py — S3 storage driver."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from services.storage_s3 import _sign_aws4, _store_s3, register


@pytest.fixture(autouse=True)
def _s3_settings(monkeypatch):
    """Ensure S3 settings exist on the settings module."""
    import settings

    monkeypatch.setattr(settings, 'S3_BUCKET', 'test-bucket', raising=False)
    monkeypatch.setattr(settings, 'S3_REGION', 'us-east-1', raising=False)
    monkeypatch.setattr(settings, 'S3_ACCESS_KEY', 'AKIATEST', raising=False)
    monkeypatch.setattr(settings, 'S3_SECRET_KEY', 'secrettest', raising=False)
    # Remove optional attrs to test defaults
    for attr in ('S3_ENDPOINT', 'S3_URL_PREFIX'):
        if hasattr(settings, attr):
            monkeypatch.delattr(settings, attr)


# ---------------------------------------------------------------------------
# register()
# ---------------------------------------------------------------------------


def test_register_adds_s3_driver():
    with patch('services.storage_s3.register_storage_driver') as mock_reg:
        register()
    mock_reg.assert_called_once_with('s3', _store_s3)


# ---------------------------------------------------------------------------
# _sign_aws4()
# ---------------------------------------------------------------------------


def test_sign_aws4_returns_authorization_header():
    """AWS4 signing produces an Authorization header."""
    headers = _sign_aws4(
        method='PUT',
        url='https://mybucket.s3.us-east-1.amazonaws.com/test.jpg',
        headers={'host': 'mybucket.s3.us-east-1.amazonaws.com', 'content-type': 'image/jpeg'},
        payload_hash='e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
        region='us-east-1',
        access_key='AKIATEST',
        secret_key='secrettest',
    )
    assert 'Authorization' in headers
    assert headers['Authorization'].startswith('AWS4-HMAC-SHA256')
    assert 'AKIATEST' in headers['Authorization']
    assert 'x-amz-date' in headers
    assert 'x-amz-content-sha256' in headers


def test_sign_aws4_includes_signed_headers():
    """Authorization header references all signed header keys."""
    headers = _sign_aws4(
        method='PUT',
        url='https://b.s3.us-east-1.amazonaws.com/f.txt',
        headers={'host': 'b.s3.us-east-1.amazonaws.com'},
        payload_hash='abc123',
        region='us-east-1',
        access_key='AK',
        secret_key='SK',
    )
    assert 'SignedHeaders=' in headers['Authorization']


# ---------------------------------------------------------------------------
# _store_s3()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_s3_default_endpoint(monkeypatch):
    """Uses default AWS S3 URL when no custom endpoint is set."""
    import settings

    monkeypatch.setattr(settings, 'S3_BUCKET', 'mybucket')
    monkeypatch.setattr(settings, 'S3_REGION', 'us-west-2')

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.put = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch('services.storage_s3.httpx.AsyncClient', return_value=mock_client):
        key, url = await _store_s3('photo.jpg', b'image-data', 'uploads')

    assert key == 'uploads/photo.jpg'
    assert url == 'https://mybucket.s3.us-west-2.amazonaws.com/uploads/photo.jpg'
    mock_client.put.assert_called_once()
    put_url = mock_client.put.call_args[0][0]
    assert 'mybucket.s3.us-west-2.amazonaws.com' in put_url


@pytest.mark.asyncio
async def test_store_s3_custom_endpoint(monkeypatch):
    """Uses custom endpoint for R2/Spaces/MinIO."""
    import settings

    monkeypatch.setattr(settings, 'S3_BUCKET', 'files')
    monkeypatch.setattr(settings, 'S3_REGION', 'auto')
    monkeypatch.setattr(settings, 'S3_ENDPOINT', 'https://r2.example.com', raising=False)

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.put = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch('services.storage_s3.httpx.AsyncClient', return_value=mock_client):
        key, url = await _store_s3('doc.pdf', b'pdf-data', 'docs')

    assert key == 'docs/doc.pdf'
    assert url == 'https://r2.example.com/files/docs/doc.pdf'


@pytest.mark.asyncio
async def test_store_s3_url_prefix(monkeypatch):
    """Uses S3_URL_PREFIX for public URL when set."""
    import settings

    monkeypatch.setattr(settings, 'S3_BUCKET', 'media')
    monkeypatch.setattr(settings, 'S3_URL_PREFIX', 'https://cdn.example.com', raising=False)

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.put = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch('services.storage_s3.httpx.AsyncClient', return_value=mock_client):
        key, url = await _store_s3('img.png', b'png-data', 'images')

    assert url == 'https://cdn.example.com/images/img.png'


@pytest.mark.asyncio
async def test_store_s3_empty_upload_dir():

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.put = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch('services.storage_s3.httpx.AsyncClient', return_value=mock_client):
        key, url = await _store_s3('file.txt', b'data', '')

    assert key == 'file.txt'
