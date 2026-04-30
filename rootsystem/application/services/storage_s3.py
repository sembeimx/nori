"""
S3-compatible storage driver for Nori.

Works with AWS S3, DigitalOcean Spaces, Cloudflare R2, MinIO, etc.

Usage in your app startup or routes.py:
    from services.storage_s3 import register
    register()

Then set STORAGE_DRIVER=s3 in your .env (or pass driver='s3' per-call).

Requires in settings/.env:
    S3_BUCKET        — bucket name
    S3_REGION        — e.g. us-east-1
    S3_ACCESS_KEY    — IAM access key
    S3_SECRET_KEY    — IAM secret key
    S3_ENDPOINT      — (optional) custom endpoint for R2/Spaces/MinIO
    S3_URL_PREFIX    — (optional) public URL prefix, defaults to https://{bucket}.s3.{region}.amazonaws.com
"""

from __future__ import annotations

import datetime
import hashlib
import hmac

import httpx
from core.conf import config
from core.http.upload import register_storage_driver

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    """Return the module-level httpx client, creating it on first use.

    Pools TCP/TLS connections across uploads — per-call
    ``async with httpx.AsyncClient()`` paid the full handshake on every
    PUT and risked socket exhaustion under load. First call registers
    ``shutdown`` with ``core.lifecycle`` so the pool closes cleanly on
    graceful ASGI shutdown.
    """
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=30.0)
        from core.lifecycle import register_shutdown

        register_shutdown('storage_s3', shutdown)
    return _client


async def shutdown() -> None:
    """Close the shared httpx client. Call from your ASGI lifespan."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _sign_aws4(
    method: str,
    url: str,
    headers: dict[str, str],
    payload_hash: str,
    region: str,
    access_key: str,
    secret_key: str,
) -> dict[str, str]:
    """Generate AWS Signature V4 authorization headers.

    This is a minimal implementation that covers the S3 PutObject and
    DeleteObject use cases. It does not support query-string signing,
    chunked uploads, or session tokens.

    Args:
        method: HTTP method (e.g. ``'PUT'``, ``'DELETE'``).
        url: Full request URL including scheme and path.
        headers: Base headers to sign (must include ``host``).
        payload_hash: SHA-256 hex digest of the request body.
        region: AWS region (e.g. ``'us-east-1'``).
        access_key: IAM access key ID.
        secret_key: IAM secret access key.

    Returns:
        A new dict with the original headers plus ``Authorization``,
        ``x-amz-date``, and ``x-amz-content-sha256``.
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    now = datetime.datetime.now(datetime.timezone.utc)
    datestamp = now.strftime('%Y%m%d')
    amz_date = now.strftime('%Y%m%dT%H%M%SZ')

    headers = {**headers, 'x-amz-date': amz_date, 'x-amz-content-sha256': payload_hash}

    signed_header_keys = sorted(headers.keys())
    signed_headers = ';'.join(signed_header_keys)

    canonical_headers = ''.join(f'{k}:{headers[k]}\n' for k in signed_header_keys)
    canonical_request = f'{method}\n{parsed.path}\n\n{canonical_headers}\n{signed_headers}\n{payload_hash}'

    scope = f'{datestamp}/{region}/s3/aws4_request'
    string_to_sign = f'AWS4-HMAC-SHA256\n{amz_date}\n{scope}\n' + hashlib.sha256(canonical_request.encode()).hexdigest()

    def _hmac(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode(), hashlib.sha256).digest()

    signing_key = _hmac(
        _hmac(_hmac(_hmac(f'AWS4{secret_key}'.encode(), datestamp), region), 's3'),
        'aws4_request',
    )

    signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()
    headers['Authorization'] = (
        f'AWS4-HMAC-SHA256 Credential={access_key}/{scope}, SignedHeaders={signed_headers}, Signature={signature}'
    )

    return headers


def _hash_and_size(source) -> tuple[str, int]:
    """Stream-hash a file-like ``source`` and return ``(sha256_hex, byte_count)``.

    Reads in 64 KB chunks then rewinds ``source`` to byte 0. AWS
    Signature V4 requires the body's SHA-256 in the signed canonical
    request, but pre-1.23 the framework hashed a Python ``bytes``
    object holding the entire upload — a 10 GB body meant 10 GB
    sitting in Python heap during ``hashlib.sha256(content)``.  This
    helper preserves the same hash output while keeping peak RAM
    bounded to one 64 KB chunk at a time.
    """
    hasher = hashlib.sha256()
    total = 0
    for chunk in iter(lambda: source.read(64 * 1024), b''):
        hasher.update(chunk)
        total += len(chunk)
    source.seek(0)
    return hasher.hexdigest(), total


def _iter_chunks(source, chunk_size: int = 64 * 1024):
    """Yield ``chunk_size``-byte chunks from ``source`` until EOF.

    Used to feed httpx ``content=`` from a SpooledTemporaryFile so
    the request body is sent in bounded chunks instead of buffered
    into a single ``bytes`` object on the way out.
    """
    while True:
        chunk = source.read(chunk_size)
        if not chunk:
            break
        yield chunk


async def _store_s3(
    filename: str,
    source,
    upload_dir: str,
) -> tuple[str, str]:
    """Upload a file to S3-compatible object storage.

    The ``upload_dir`` argument is used as the key prefix (e.g.
    ``uploads/abc123.jpg``). Connection details are read from
    ``settings``: ``S3_BUCKET``, ``S3_REGION``, ``S3_ACCESS_KEY``,
    ``S3_SECRET_KEY``, and optionally ``S3_ENDPOINT`` and
    ``S3_URL_PREFIX``.

    Args:
        filename: Generated filename (e.g. ``'abc123.jpg'``).
        source: File-like object positioned at byte 0 (typically a
            :class:`tempfile.SpooledTemporaryFile` from
            :func:`core.http.upload._spool_body`).  The driver
            stream-hashes ``source`` for the AWS V4 signature, then
            stream-uploads the body via httpx — the full payload is
            never materialised as a single ``bytes`` object.
        upload_dir: Key prefix / virtual directory.

    Returns:
        A tuple of ``(object_key, public_url)``.

    Raises:
        httpx.HTTPStatusError: If the storage API returns a non-2xx
            response.
    """
    bucket = config.S3_BUCKET
    region = config.get('S3_REGION', 'us-east-1')
    access_key = config.S3_ACCESS_KEY
    secret_key = config.S3_SECRET_KEY

    endpoint = config.get('S3_ENDPOINT', None)
    url_prefix = config.get('S3_URL_PREFIX', None)

    # Build the object key using upload_dir as prefix
    key = f'{upload_dir.strip("/")}/{filename}' if upload_dir else filename

    # Build endpoint URL
    if endpoint:
        put_url = f'{endpoint.rstrip("/")}/{bucket}/{key}'
    else:
        put_url = f'https://{bucket}.s3.{region}.amazonaws.com/{key}'

    # Stream-hash the source so we never hold the full body in RAM
    # during signing. The hash + length feed both sigv4 and the
    # explicit Content-Length below (which keeps httpx from falling
    # back to chunked transfer-encoding, which S3 does not accept on
    # plain PutObject).
    payload_hash, size = _hash_and_size(source)
    content_type = 'application/octet-stream'

    headers = _sign_aws4(
        method='PUT',
        url=put_url,
        headers={'host': put_url.split('/')[2], 'content-type': content_type},
        payload_hash=payload_hash,
        region=region,
        access_key=access_key,
        secret_key=secret_key,
    )
    headers['content-type'] = content_type
    headers['content-length'] = str(size)

    client = _get_client()
    resp = await client.put(put_url, content=_iter_chunks(source), headers=headers)
    resp.raise_for_status()

    # Public URL
    if url_prefix:
        public_url = f'{url_prefix.rstrip("/")}/{key}'
    elif endpoint:
        public_url = f'{endpoint.rstrip("/")}/{bucket}/{key}'
    else:
        public_url = f'https://{bucket}.s3.{region}.amazonaws.com/{key}'

    return key, public_url


def register():
    """Register the S3 storage driver."""
    register_storage_driver('s3', _store_s3)
