"""Tests for services/storage_s3.py — S3 storage driver."""

from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from services.storage_s3 import _hash_and_size, _sign_aws4, _store_s3, register


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


@pytest.fixture(autouse=True)
def _reset_client():
    """Reset the module-level httpx client between tests."""
    import services.storage_s3 as s3_mod

    s3_mod._client = None
    yield
    s3_mod._client = None


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

    with patch('services.storage_s3._get_client', return_value=mock_client):
        key, url = await _store_s3('photo.jpg', io.BytesIO(b'image-data'), 'uploads')

    assert key == 'uploads/photo.jpg'
    assert url == 'https://mybucket.s3.us-west-2.amazonaws.com/uploads/photo.jpg'
    mock_client.put.assert_called_once()
    put_url = mock_client.put.call_args[0][0]
    assert 'mybucket.s3.us-west-2.amazonaws.com' in put_url
    # Post-1.23 the body is sent as a streaming generator with an explicit
    # Content-Length, not as raw bytes — guard against a regression that
    # would re-introduce the RAM exhaustion vector.
    sent_content = mock_client.put.call_args.kwargs['content']
    assert not isinstance(sent_content, (bytes, bytearray)), (
        'S3 driver buffered the upload into bytes — RAM regression'
    )
    sent_headers = mock_client.put.call_args.kwargs['headers']
    assert sent_headers['content-length'] == str(len(b'image-data'))


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

    with patch('services.storage_s3._get_client', return_value=mock_client):
        key, url = await _store_s3('doc.pdf', io.BytesIO(b'pdf-data'), 'docs')

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

    with patch('services.storage_s3._get_client', return_value=mock_client):
        key, url = await _store_s3('img.png', io.BytesIO(b'png-data'), 'images')

    assert url == 'https://cdn.example.com/images/img.png'


@pytest.mark.asyncio
async def test_store_s3_empty_upload_dir():

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.put = AsyncMock(return_value=mock_response)

    with patch('services.storage_s3._get_client', return_value=mock_client):
        key, url = await _store_s3('file.txt', io.BytesIO(b'data'), '')

    assert key == 'file.txt'


# ---------------------------------------------------------------------------
# _hash_and_size() — streaming SHA-256
# ---------------------------------------------------------------------------


def test_hash_and_size_matches_sha256_of_full_body():
    """Streaming hash must equal hashlib.sha256(full_body).hexdigest().

    AWS V4 signing breaks if the body's hash differs by even one bit, so
    the streaming hasher must produce the byte-for-byte same digest as
    the previous in-memory implementation. Exercise across a chunk
    boundary (>64 KB) to make sure we don't drop the tail.
    """
    import hashlib

    body = (b'A' * (64 * 1024)) + (b'B' * 1234)  # spans a chunk boundary
    expected = hashlib.sha256(body).hexdigest()

    src = io.BytesIO(body)
    digest, size = _hash_and_size(src)

    assert digest == expected
    assert size == len(body)
    assert src.tell() == 0, 'source must be rewound after hashing for the upload step'
