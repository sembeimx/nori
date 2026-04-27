"""Tests for services/storage_gcs.py — Google Cloud Storage driver."""

from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import services.storage_gcs as gcs_mod
from services.storage_gcs import (
    _b64url,
    _build_jwt,
    _get_access_token,
    _load_credentials,
    _store_gcs,
    register,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_token_cache():
    """Clear the module-level token cache between tests."""
    gcs_mod._token_cache['token'] = None
    gcs_mod._token_cache['expires_at'] = 0.0
    yield
    gcs_mod._token_cache['token'] = None
    gcs_mod._token_cache['expires_at'] = 0.0


@pytest.fixture
def rsa_keypair():
    """Generate a throwaway RSA keypair and return the PEM-encoded private key."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return pem, key


@pytest.fixture
def fake_credentials(rsa_keypair):
    """A plausible service account JSON dict."""
    pem, _ = rsa_keypair
    return {
        'type': 'service_account',
        'project_id': 'nori-test',
        'private_key_id': 'abc123',
        'private_key': pem,
        'client_email': 'nori-test@nori-test.iam.gserviceaccount.com',
        'client_id': '123456',
        'token_uri': 'https://oauth2.googleapis.com/token',
    }


@pytest.fixture(autouse=True)
def _gcs_settings(monkeypatch):
    """Ensure GCS settings exist on the settings module."""
    import settings

    monkeypatch.setattr(settings, 'GCS_BUCKET', 'test-bucket', raising=False)
    for attr in ('GCS_URL_PREFIX', 'GCS_CREDENTIALS_FILE', 'GCS_CREDENTIALS_JSON'):
        if hasattr(settings, attr):
            monkeypatch.delattr(settings, attr)


# ---------------------------------------------------------------------------
# register()
# ---------------------------------------------------------------------------


def test_register_adds_gcs_driver():
    with patch('services.storage_gcs.register_storage_driver') as mock_reg:
        register()
    mock_reg.assert_called_once_with('gcs', _store_gcs)


# ---------------------------------------------------------------------------
# _b64url()
# ---------------------------------------------------------------------------


def test_b64url_strips_padding():
    assert _b64url(b'hi') == 'aGk'  # standard b64 would be 'aGk='


def test_b64url_uses_url_safe_alphabet():
    data = b'\xfb\xff\xbf'  # produces + and / in standard b64
    result = _b64url(data)
    assert '+' not in result
    assert '/' not in result


# ---------------------------------------------------------------------------
# _load_credentials()
# ---------------------------------------------------------------------------


def test_load_credentials_from_file(tmp_path, fake_credentials, monkeypatch):
    import settings

    creds_path = tmp_path / 'sa.json'
    creds_path.write_text(json.dumps(fake_credentials))
    monkeypatch.setattr(settings, 'GCS_CREDENTIALS_FILE', str(creds_path), raising=False)

    loaded = _load_credentials()
    assert loaded['client_email'] == fake_credentials['client_email']


def test_load_credentials_from_json_env(fake_credentials, monkeypatch):
    import settings

    monkeypatch.setattr(settings, 'GCS_CREDENTIALS_JSON', json.dumps(fake_credentials), raising=False)

    loaded = _load_credentials()
    assert loaded['client_email'] == fake_credentials['client_email']


def test_load_credentials_file_takes_precedence(tmp_path, fake_credentials, monkeypatch):
    import settings

    creds_path = tmp_path / 'sa.json'
    creds_path.write_text(json.dumps({**fake_credentials, 'client_email': 'from-file@x.iam'}))
    monkeypatch.setattr(settings, 'GCS_CREDENTIALS_FILE', str(creds_path), raising=False)
    monkeypatch.setattr(
        settings,
        'GCS_CREDENTIALS_JSON',
        json.dumps({**fake_credentials, 'client_email': 'from-env@x.iam'}),
        raising=False,
    )

    loaded = _load_credentials()
    assert loaded['client_email'] == 'from-file@x.iam'


def test_load_credentials_raises_when_missing():
    with pytest.raises(RuntimeError, match='GCS_CREDENTIALS'):
        _load_credentials()


# ---------------------------------------------------------------------------
# _build_jwt()
# ---------------------------------------------------------------------------


def test_build_jwt_returns_three_part_token(rsa_keypair):
    pem, _ = rsa_keypair
    jwt = _build_jwt(
        client_email='sa@nori-test.iam.gserviceaccount.com',
        private_key_pem=pem,
        token_uri='https://oauth2.googleapis.com/token',
    )
    parts = jwt.split('.')
    assert len(parts) == 3


def test_build_jwt_header_claims_are_valid(rsa_keypair):
    pem, _ = rsa_keypair
    jwt = _build_jwt(
        client_email='sa@nori.iam.gserviceaccount.com',
        private_key_pem=pem,
        token_uri='https://oauth2.googleapis.com/token',
    )
    header_b64, claims_b64, _sig = jwt.split('.')

    def _decode(s: str) -> dict:
        padded = s + '=' * (-len(s) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))

    header = _decode(header_b64)
    claims = _decode(claims_b64)

    assert header == {'alg': 'RS256', 'typ': 'JWT'}
    assert claims['iss'] == 'sa@nori.iam.gserviceaccount.com'
    assert claims['aud'] == 'https://oauth2.googleapis.com/token'
    assert claims['scope'] == 'https://www.googleapis.com/auth/devstorage.read_write'
    assert claims['exp'] - claims['iat'] == 3600


def test_build_jwt_signature_verifies(rsa_keypair):
    """Generated signature is verifiable with the corresponding public key."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    pem, key = rsa_keypair
    jwt = _build_jwt(
        client_email='sa@x.iam',
        private_key_pem=pem,
        token_uri='https://oauth2.googleapis.com/token',
    )
    header_b64, claims_b64, sig_b64 = jwt.split('.')
    signing_input = f'{header_b64}.{claims_b64}'.encode()
    signature = base64.urlsafe_b64decode(sig_b64 + '=' * (-len(sig_b64) % 4))

    # Raises InvalidSignature if the signature does not verify
    key.public_key().verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())


# ---------------------------------------------------------------------------
# _get_access_token()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_access_token_fetches_and_caches(fake_credentials, monkeypatch):
    import settings

    monkeypatch.setattr(settings, 'GCS_CREDENTIALS_JSON', json.dumps(fake_credentials), raising=False)

    token_response = MagicMock()
    token_response.raise_for_status = MagicMock()
    token_response.json = MagicMock(
        return_value={
            'access_token': 'ya29.test-token',
            'expires_in': 3600,
        }
    )

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=token_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch('services.storage_gcs.httpx.AsyncClient', return_value=mock_client):
        tok1 = await _get_access_token()
        tok2 = await _get_access_token()

    assert tok1 == 'ya29.test-token'
    assert tok2 == 'ya29.test-token'
    mock_client.post.assert_called_once()  # second call used the cache


@pytest.mark.asyncio
async def test_get_access_token_refreshes_when_expired(fake_credentials, monkeypatch):
    import settings

    monkeypatch.setattr(settings, 'GCS_CREDENTIALS_JSON', json.dumps(fake_credentials), raising=False)

    # Pre-seed the cache with an expired token
    gcs_mod._token_cache['token'] = 'old-token'
    gcs_mod._token_cache['expires_at'] = 0.0  # expired

    token_response = MagicMock()
    token_response.raise_for_status = MagicMock()
    token_response.json = MagicMock(
        return_value={
            'access_token': 'new-token',
            'expires_in': 3600,
        }
    )

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=token_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch('services.storage_gcs.httpx.AsyncClient', return_value=mock_client):
        tok = await _get_access_token()

    assert tok == 'new-token'


@pytest.mark.asyncio
async def test_get_access_token_posts_jwt_bearer_grant(fake_credentials, monkeypatch):
    import settings

    monkeypatch.setattr(settings, 'GCS_CREDENTIALS_JSON', json.dumps(fake_credentials), raising=False)

    token_response = MagicMock()
    token_response.raise_for_status = MagicMock()
    token_response.json = MagicMock(return_value={'access_token': 't', 'expires_in': 3600})

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=token_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch('services.storage_gcs.httpx.AsyncClient', return_value=mock_client):
        await _get_access_token()

    call_url = mock_client.post.call_args[0][0]
    call_data = mock_client.post.call_args.kwargs['data']
    assert call_url == 'https://oauth2.googleapis.com/token'
    assert call_data['grant_type'] == 'urn:ietf:params:oauth:grant-type:jwt-bearer'
    assert call_data['assertion'].count('.') == 2  # a JWT


# ---------------------------------------------------------------------------
# _store_gcs()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_gcs_default_url(monkeypatch):
    import settings

    monkeypatch.setattr(settings, 'GCS_BUCKET', 'mybucket')

    async def _fake_token():
        return 'fake-token'

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.put = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch('services.storage_gcs._get_access_token', _fake_token),
        patch('services.storage_gcs.httpx.AsyncClient', return_value=mock_client),
    ):
        key, url = await _store_gcs('photo.jpg', b'image-data', 'uploads')

    assert key == 'uploads/photo.jpg'
    assert url == 'https://storage.googleapis.com/mybucket/uploads/photo.jpg'

    put_url = mock_client.put.call_args[0][0]
    assert put_url == 'https://storage.googleapis.com/mybucket/uploads/photo.jpg'
    headers = mock_client.put.call_args.kwargs['headers']
    assert headers['Authorization'] == 'Bearer fake-token'
    assert headers['Content-Type'] == 'application/octet-stream'


@pytest.mark.asyncio
async def test_store_gcs_url_prefix(monkeypatch):
    import settings

    monkeypatch.setattr(settings, 'GCS_BUCKET', 'media')
    monkeypatch.setattr(settings, 'GCS_URL_PREFIX', 'https://cdn.example.com', raising=False)

    async def _fake_token():
        return 'fake-token'

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.put = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch('services.storage_gcs._get_access_token', _fake_token),
        patch('services.storage_gcs.httpx.AsyncClient', return_value=mock_client),
    ):
        key, url = await _store_gcs('img.png', b'png-data', 'images')

    assert key == 'images/img.png'
    assert url == 'https://cdn.example.com/images/img.png'


@pytest.mark.asyncio
async def test_store_gcs_empty_upload_dir(monkeypatch):
    import settings

    monkeypatch.setattr(settings, 'GCS_BUCKET', 'mybucket')

    async def _fake_token():
        return 'fake-token'

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.put = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch('services.storage_gcs._get_access_token', _fake_token),
        patch('services.storage_gcs.httpx.AsyncClient', return_value=mock_client),
    ):
        key, url = await _store_gcs('file.txt', b'data', '')

    assert key == 'file.txt'
    assert url == 'https://storage.googleapis.com/mybucket/file.txt'
