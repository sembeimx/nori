"""Multi-driver file upload with validation and magic-byte content verification.

Provides ``save_upload()`` for secure file handling with three layers of
validation:

1. **Extension** — only extensions in ``allowed_types`` are accepted.
2. **MIME type** — the client-declared ``Content-Type`` must match the
   expected MIME for the extension (catches simple mismatches).
3. **Magic bytes** — the **actual file content** is inspected for known
   file signatures (JPEG ``\\xff\\xd8\\xff``, PNG ``\\x89PNG``, etc.).
   This prevents an attacker from uploading a disguised file by simply
   renaming it and setting a fake ``Content-Type`` header.

Quick start::

    from core.http.upload import save_upload, UploadResult, UploadError

    result = await save_upload(
        file,
        allowed_types=['jpg', 'png', 'pdf'],
        max_size=5 * 1024 * 1024,  # 5 MB
    )
    # result.filename, result.path, result.url, result.size, result.original_name

    # Override driver per-call:
    result = await save_upload(file, driver='s3')

    # Register a custom storage driver:
    from core.http.upload import register_storage_driver

    async def my_driver(filename, content, upload_dir):
        ...
        return path, url

    register_storage_driver('custom', my_driver)

Security note:
    Magic-byte verification is implemented in pure Python (no external
    dependencies like ``python-magic`` / ``libmagic``) to stay consistent
    with Nori's "Keep it Native" philosophy.  It covers the most common
    file types (JPEG, PNG, GIF, PDF, WebP).  For exotic formats the check
    is skipped gracefully — the extension and MIME checks still apply.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from core.conf import config

_MIME_MAP: dict[str, str] = {
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'png': 'image/png',
    'gif': 'image/gif',
    'pdf': 'application/pdf',
    'webp': 'image/webp',
    'svg': 'image/svg+xml',
}

# ---------------------------------------------------------------------------
# Magic byte signatures for content-based file type verification.
#
# Each entry maps a file extension to a tuple of byte prefixes that are
# valid for that type.  When a file is uploaded, the first bytes of its
# content are compared against these signatures.  If the content does NOT
# start with any of the expected prefixes, the upload is rejected — even
# if the extension and Content-Type header look correct.
#
# This is a pure-Python approach that covers ~90% of real-world uploads
# without requiring heavy C dependencies like libmagic.
# ---------------------------------------------------------------------------
_MAGIC_BYTES: dict[str, tuple[bytes, ...]] = {
    'jpg': (b'\xff\xd8\xff',),
    'jpeg': (b'\xff\xd8\xff',),
    'png': (b'\x89PNG\r\n\x1a\n',),
    'gif': (b'GIF87a', b'GIF89a'),
    'pdf': (b'%PDF',),
    'webp': (b'RIFF',),  # Full check: bytes 8-12 must be WEBP (see _validate_magic_bytes)
}


class UploadError(Exception):
    """Raised when a file upload fails validation."""


@dataclass
class UploadResult:
    """Result of a successful file upload.

    Attributes:
        filename: Generated unique filename (e.g. ``'a1b2c3.jpg'``).
        path: Full path or object key where the file was stored.
        url: Public URL to access the file.
        size: File size in bytes.
        original_name: Original filename as provided by the client.
    """

    filename: str
    path: str
    url: str
    size: int
    original_name: str


def _validate_extension(filename: str, allowed_types: list[str]) -> str:
    """Validate and return file extension (lowercase, without dot)."""
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in allowed_types:
        raise UploadError(f"Extension '.{ext}' not allowed. Allowed: {', '.join(allowed_types)}")
    return ext


def _validate_mime_type(content_type: str | None, ext: str) -> None:
    """Validate that the client-declared MIME type matches the extension.

    This checks the ``Content-Type`` header sent by the browser.  It is a
    first line of defence but **not sufficient on its own** because the
    header is trivially spoofable.  The real content verification happens
    in ``_validate_magic_bytes()``.
    """
    expected = _MIME_MAP.get(ext)
    # Strip charset/parameters from Content-Type before comparison
    if expected and content_type:
        base_type = content_type.split(';')[0].strip()
        if base_type != expected:
            raise UploadError(f"MIME type '{base_type}' does not match extension '.{ext}' (expected '{expected}')")


def _validate_magic_bytes(content: bytes, ext: str) -> None:
    """Verify that file content matches expected magic-byte signatures.

    Compares the first bytes of *content* against known file signatures
    for the given extension.  If the extension has a known signature in
    ``_MAGIC_BYTES`` and the content does not match **any** of them, the
    upload is rejected with an ``UploadError``.

    For extensions without a known signature (e.g. ``svg``, ``csv``),
    this check is skipped — the extension and MIME validations still apply.

    Args:
        content: Raw file bytes (only the beginning is inspected).
        ext: Lowercase file extension without dot.

    Raises:
        UploadError: If the content does not match the expected file
            signature for *ext*.
    """
    signatures = _MAGIC_BYTES.get(ext)
    if not signatures:
        return  # No known signature for this extension — skip gracefully
    if not any(content.startswith(sig) for sig in signatures):
        raise UploadError(f"File content does not match expected format for '.{ext}' (magic byte verification failed)")
    # WebP: RIFF container must have WEBP identifier at bytes 8-12
    if ext == 'webp' and len(content) >= 12 and content[8:12] != b'WEBP':
        raise UploadError("File content does not match expected format for '.webp' (RIFF container is not WebP)")


def _generate_filename(ext: str) -> str:
    """Generate a unique filename with UUID."""
    return f'{uuid.uuid4().hex}.{ext}'


# ---------------------------------------------------------------------------
# Storage drivers
# ---------------------------------------------------------------------------


def _write_to_disk(file_path: str, content: bytes, upload_dir: str) -> None:
    """Synchronous mkdir + write — invoked from a thread executor so the
    event loop stays unblocked during local-disk I/O. Do not call from an
    async context directly; route through :func:`_store_local`."""
    Path(upload_dir).mkdir(parents=True, exist_ok=True)
    Path(file_path).write_bytes(content)


async def _store_local(
    filename: str,
    content: bytes,
    upload_dir: str,
) -> tuple[str, str]:
    """Store a file on the local filesystem.

    Creates ``upload_dir`` if it doesn't exist. This is the default
    storage driver. The blocking mkdir + write are offloaded via
    :func:`asyncio.to_thread` so that disk I/O does not stall the event
    loop — under load on slow disks or network filesystems a multi-MB
    write would otherwise hijack the loop for tens of milliseconds.

    Args:
        filename: Generated filename (e.g. ``'abc123.jpg'``).
        content: Raw file bytes.
        upload_dir: Directory to save into.

    Returns:
        A tuple of ``(absolute_path, url)`` where url is
        ``/uploads/{filename}``.
    """
    file_path = os.path.join(upload_dir, filename)
    await asyncio.to_thread(_write_to_disk, file_path, content, upload_dir)
    return file_path, f'/uploads/{filename}'


_DRIVERS: dict[str, Callable] = {
    'local': _store_local,
}


def register_storage_driver(name: str, handler: Callable) -> None:
    """Register a custom storage driver.

    The handler must be an async callable with signature:
        async def handler(filename: str, content: bytes, upload_dir: str) -> tuple[str, str]

    It must return a tuple of (path, url).
    """
    _DRIVERS[name] = handler


def get_storage_drivers() -> set[str]:
    """Return the names of all registered storage drivers."""
    return set(_DRIVERS)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def save_upload(
    file,
    *,
    allowed_types: list[str] | None = None,
    max_size: int | None = None,
    upload_dir: str | None = None,
    driver: str | None = None,
) -> UploadResult:
    """Validate and save an uploaded file using the configured storage driver.

    Applies three layers of validation before storing:

    1. **Extension check** — rejects files whose extension is not in
       *allowed_types*.
    2. **MIME type check** — rejects files whose client-declared
       ``Content-Type`` doesn't match the expected MIME for the extension.
    3. **Magic byte check** — inspects the **actual file content** for
       known file signatures (e.g. JPEG ``\\xff\\xd8\\xff``, PNG
       ``\\x89PNG``).  This prevents attackers from uploading disguised
       files by renaming them and spoofing the ``Content-Type`` header.

    Args:
        file: Starlette ``UploadFile`` instance.
        allowed_types: List of allowed extensions (e.g. ``['jpg', 'png']``).
        max_size: Max file size in bytes.
        upload_dir: Directory or prefix to save into (default:
            ``settings.UPLOAD_DIR``).
        driver: Override the default storage driver for this call.

    Returns:
        ``UploadResult`` with file metadata.

    Raises:
        UploadError: If any validation layer fails (extension, MIME,
            magic bytes, or size).
        ValueError: If the requested storage driver is not registered.
    """
    if allowed_types is None:
        allowed_types = list(_MIME_MAP.keys())
    if max_size is None:
        max_size = config.get('UPLOAD_MAX_SIZE', 10 * 1024 * 1024)
    if upload_dir is None:
        upload_dir = config.get('UPLOAD_DIR', 'uploads')

    original_name = file.filename or 'unnamed'

    # Validate extension
    ext = _validate_extension(original_name, allowed_types)

    # Validate MIME type
    _validate_mime_type(getattr(file, 'content_type', None), ext)

    # Read content and validate size
    content = await file.read()
    if len(content) == 0:
        raise UploadError('File is empty')
    if len(content) > max_size:
        raise UploadError(f'File size ({len(content)} bytes) exceeds max ({max_size} bytes)')

    # Verify actual file content via magic bytes
    _validate_magic_bytes(content, ext)

    # Generate unique name and dispatch to driver
    filename = _generate_filename(ext)

    driver_name = driver or config.get('STORAGE_DRIVER', 'local')
    handler = _DRIVERS.get(driver_name)
    if handler is None:
        available = ', '.join(sorted(_DRIVERS))
        raise ValueError(f"Unknown storage driver '{driver_name}'. Available drivers: {available}")

    file_path, url = await handler(filename, content, upload_dir)

    return UploadResult(
        filename=filename,
        path=file_path,
        url=url,
        size=len(content),
        original_name=original_name,
    )
