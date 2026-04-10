from __future__ import annotations

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

import httpx
import hashlib
import hmac
import datetime

from core.conf import config
from core.http.upload import register_storage_driver


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
    now = datetime.datetime.utcnow()
    datestamp = now.strftime('%Y%m%d')
    amz_date = now.strftime('%Y%m%dT%H%M%SZ')

    headers = {**headers, 'x-amz-date': amz_date, 'x-amz-content-sha256': payload_hash}

    signed_header_keys = sorted(headers.keys())
    signed_headers = ';'.join(signed_header_keys)

    canonical_headers = ''.join(f'{k}:{headers[k]}\n' for k in signed_header_keys)
    canonical_request = (
        f"{method}\n{parsed.path}\n\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
    )

    scope = f"{datestamp}/{region}/s3/aws4_request"
    string_to_sign = (
        f"AWS4-HMAC-SHA256\n{amz_date}\n{scope}\n"
        + hashlib.sha256(canonical_request.encode()).hexdigest()
    )

    def _hmac(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode(), hashlib.sha256).digest()

    signing_key = _hmac(
        _hmac(_hmac(_hmac(f'AWS4{secret_key}'.encode(), datestamp), region), 's3'),
        'aws4_request',
    )

    signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()
    headers['Authorization'] = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    return headers


async def _store_s3(
    filename: str,
    content: bytes,
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
        content: Raw file bytes.
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
    key = f"{upload_dir.strip('/')}/{filename}" if upload_dir else filename

    # Build endpoint URL
    if endpoint:
        put_url = f"{endpoint.rstrip('/')}/{bucket}/{key}"
    else:
        put_url = f"https://{bucket}.s3.{region}.amazonaws.com/{key}"

    payload_hash = hashlib.sha256(content).hexdigest()
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

    async with httpx.AsyncClient() as client:
        resp = await client.put(put_url, content=content, headers=headers)
        resp.raise_for_status()

    # Public URL
    if url_prefix:
        public_url = f"{url_prefix.rstrip('/')}/{key}"
    elif endpoint:
        public_url = f"{endpoint.rstrip('/')}/{bucket}/{key}"
    else:
        public_url = f"https://{bucket}.s3.{region}.amazonaws.com/{key}"

    return key, public_url


def register():
    """Register the S3 storage driver."""
    register_storage_driver('s3', _store_s3)
