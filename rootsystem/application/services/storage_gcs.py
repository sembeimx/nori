"""
Google Cloud Storage driver for Nori.

Uses service account authentication (JWT → OAuth2 access token) to upload
objects via the native GCS XML API. No boto3, no google-cloud-storage SDK.

Usage in your app startup or routes.py:
    from services.storage_gcs import register
    register()

Then set STORAGE_DRIVER=gcs in your .env (or pass driver='gcs' per-call).

Requires in settings/.env:
    GCS_BUCKET              — bucket name
    GCS_CREDENTIALS_FILE    — path to service account JSON key
        OR
    GCS_CREDENTIALS_JSON    — service account JSON as a string
    GCS_URL_PREFIX          — (optional) public URL prefix, defaults to
                              https://storage.googleapis.com/{bucket}

Notes:
    * The object is uploaded privately by default — configure bucket-level
      public access or an object ACL if you need the returned URL to be
      publicly reachable. For private buckets, use GCS_URL_PREFIX to point
      at a CDN that handles signing.
    * Requires the optional ``cryptography`` package for RS256 JWT signing::

          pip install cryptography
"""

from __future__ import annotations

import asyncio
import base64
import json
import time

import httpx
from core.conf import config
from core.http.upload import register_storage_driver

_TOKEN_SCOPE = 'https://www.googleapis.com/auth/devstorage.read_write'  # noqa: S105 — public GCS scope identifier, not a secret

_token_cache: dict = {'token': None, 'expires_at': 0.0}
_token_lock = asyncio.Lock()


def _b64url(data: bytes) -> str:
    """Base64 URL-safe encode without padding (per RFC 7515)."""
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def _load_credentials() -> dict:
    """Load the service account JSON from file or env variable.

    Returns:
        Parsed service account dict with at minimum ``client_email``,
        ``private_key``, and ``token_uri``.

    Raises:
        RuntimeError: If neither ``GCS_CREDENTIALS_FILE`` nor
            ``GCS_CREDENTIALS_JSON`` is configured.
    """
    creds_file = config.get('GCS_CREDENTIALS_FILE', None)
    creds_json = config.get('GCS_CREDENTIALS_JSON', None)

    if creds_file:
        with open(creds_file, encoding='utf-8') as f:
            return json.load(f)
    if creds_json:
        return json.loads(creds_json)

    raise RuntimeError('GCS driver requires GCS_CREDENTIALS_FILE or GCS_CREDENTIALS_JSON')


def _build_jwt(client_email: str, private_key_pem: str, token_uri: str) -> str:
    """Build and sign a JWT for the Google OAuth2 token exchange.

    Args:
        client_email: Service account email (``iss`` claim).
        private_key_pem: PEM-encoded RSA private key from the service account.
        token_uri: Google token endpoint (``aud`` claim).

    Returns:
        Signed JWT as a compact ``header.claims.signature`` string.
    """
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

    now = int(time.time())
    header = {'alg': 'RS256', 'typ': 'JWT'}
    claims = {
        'iss': client_email,
        'scope': _TOKEN_SCOPE,
        'aud': token_uri,
        'iat': now,
        'exp': now + 3600,
    }

    header_b64 = _b64url(json.dumps(header, separators=(',', ':')).encode())
    claims_b64 = _b64url(json.dumps(claims, separators=(',', ':')).encode())
    signing_input = f'{header_b64}.{claims_b64}'

    private_key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
    # GCS service-account keys are RSA. load_pem_private_key returns a union of
    # RSA/DSA/DH/Ed25519/Ed448/X25519/X448 — only RSA exposes the (data, padding,
    # hash) sign signature this code uses, so narrow before signing.
    if not isinstance(private_key, RSAPrivateKey):
        raise RuntimeError('GCS service account private key must be RSA')
    signature = private_key.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())

    return f'{signing_input}.{_b64url(signature)}'


async def _get_access_token() -> str:
    """Return a cached GCS access token, refreshing if near expiry.

    Concurrent callers reuse the same in-flight refresh via
    ``_token_lock``. Tokens are considered stale 60 s before their
    advertised expiry to avoid mid-request expiration.
    """
    now = time.time()
    if _token_cache['token'] and _token_cache['expires_at'] > now + 60:
        return _token_cache['token']

    async with _token_lock:
        now = time.time()
        if _token_cache['token'] and _token_cache['expires_at'] > now + 60:
            return _token_cache['token']

        creds = _load_credentials()
        jwt = _build_jwt(
            client_email=creds['client_email'],
            private_key_pem=creds['private_key'],
            token_uri=creds['token_uri'],
        )

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                creds['token_uri'],
                data={
                    'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
                    'assertion': jwt,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        _token_cache['token'] = data['access_token']
        _token_cache['expires_at'] = time.time() + int(data.get('expires_in', 3600))
        return _token_cache['token']


async def _store_gcs(
    filename: str,
    content: bytes,
    upload_dir: str,
) -> tuple[str, str]:
    """Upload a file to Google Cloud Storage.

    The ``upload_dir`` is used as the key prefix (e.g. ``uploads/abc123.jpg``).
    Credentials and bucket are read from ``config``: ``GCS_BUCKET``,
    ``GCS_CREDENTIALS_FILE`` or ``GCS_CREDENTIALS_JSON``, and optionally
    ``GCS_URL_PREFIX``.

    Args:
        filename: Generated filename (e.g. ``'abc123.jpg'``).
        content: Raw file bytes.
        upload_dir: Key prefix / virtual directory.

    Returns:
        Tuple of ``(object_key, public_url)``.

    Raises:
        httpx.HTTPStatusError: If the storage API returns a non-2xx response.
        RuntimeError: If credentials are missing.
    """
    bucket = config.GCS_BUCKET
    url_prefix = config.get('GCS_URL_PREFIX', None)

    key = f'{upload_dir.strip("/")}/{filename}' if upload_dir else filename

    token = await _get_access_token()
    put_url = f'https://storage.googleapis.com/{bucket}/{key}'
    content_type = 'application/octet-stream'

    async with httpx.AsyncClient() as client:
        resp = await client.put(
            put_url,
            content=content,
            headers={
                'Authorization': f'Bearer {token}',
                'Content-Type': content_type,
            },
        )
        resp.raise_for_status()

    if url_prefix:
        public_url = f'{url_prefix.rstrip("/")}/{key}'
    else:
        public_url = put_url

    return key, public_url


def register():
    """Register the GCS storage driver."""
    register_storage_driver('gcs', _store_gcs)
