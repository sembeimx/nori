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
import re
import shutil
import tempfile
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

# Extensions intentionally excluded from the default ``allowed_types``
# returned by :func:`_default_allowed_types`. SVG is the canonical
# example: an SVG is XML, can carry ``<script>`` and ``on*`` event
# handlers, and executes them when a browser renders it inline (as
# ``<object>``, ``<embed>``, or a direct link served with
# ``Content-Type: image/svg+xml``). The framework cannot safely accept
# arbitrary SVG content without parsing the document, so the safe
# default is "off" — projects that need SVG opt in explicitly via
# ``allowed_types=['svg', ...]`` and accept the responsibility of
# either sanitising the content server-side (e.g. ``bleach`` with an
# SVG whitelist) or serving uploads with ``Content-Type: text/plain``.
# When opt-in IS used, :func:`_validate_svg_content` provides defence
# in depth by rejecting the most common script vectors.
_UNSAFE_BY_DEFAULT: frozenset[str] = frozenset({'svg'})


def _default_allowed_types() -> list[str]:
    """Default extension allowlist when ``save_upload`` is called
    without an explicit ``allowed_types``.

    Excludes anything in :data:`_UNSAFE_BY_DEFAULT` so a developer who
    forgets to specify the list cannot silently inherit a stored-XSS
    surface (the v1.33 / pre-v1.34 default included ``svg``).
    """
    return [ext for ext in _MIME_MAP if ext not in _UNSAFE_BY_DEFAULT]


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
    # SVG is XML; ``<?xml`` and ``<svg`` cover essentially every
    # real-world SVG. The prefix check is a sanity guard ONLY — an
    # attacker can trivially supply ``<?xml`` and still embed
    # ``<script>`` further down. The substantive defence is
    # :func:`_validate_svg_content`, which scans the body for script
    # and event-handler vectors. SVG is opt-in (excluded from
    # ``_default_allowed_types``), so this entry only fires for
    # projects that explicitly accepted the format.
    'svg': (b'<?xml', b'<svg'),
}


# SVG content patterns that turn an SVG into an XSS payload when the
# document is rendered inline by a browser. The framework rejects an
# upload containing ANY of these — this is intentionally conservative
# (no attempt to sanitise the document; a denied upload is safer than
# a half-cleaned one). Patterns are applied lowercased so the check is
# case-insensitive.
_SVG_FORBIDDEN_TAGS: tuple[bytes, ...] = (
    b'<script',
    b'<foreignobject',  # smuggles HTML — including <script> — into SVG
    b'<iframe',
    b'<embed',
    b'<object',
)

# ``<svg ... onload="...">`` style event handlers. The pattern matches
# any whitespace-bounded ``on<lower>=`` substring; that catches
# ``onload``, ``onclick``, ``onerror``, ``onmouseover``, and the long
# tail without enumerating every event name.
_SVG_EVENT_HANDLER_RE = re.compile(rb'\son[a-z]+\s*=', re.IGNORECASE)

# Cap on how many bytes we scan for SVG content checks. Legitimate SVG
# icons / diagrams are well under this; extremely large SVGs are an
# uncommon and suspicious shape. The cap also bounds the worst-case
# CPU cost of the regex scan so a maliciously-crafted multi-MB SVG
# cannot become a DoS vector for the validator itself.
_SVG_SCAN_LIMIT: int = 256 * 1024  # 256 KB


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


def _validate_svg_content(content: bytes) -> None:
    """Reject SVG payloads that would execute scripts when rendered inline.

    The check inspects up to :data:`_SVG_SCAN_LIMIT` bytes (legitimate
    SVG icons are far smaller; the cap bounds worst-case scan CPU
    against a maliciously-large input). Two passes:

    * **Forbidden tags** — ``<script>``, ``<foreignObject>``,
      ``<iframe>``, ``<embed>``, ``<object>``. Any presence aborts.
      ``<foreignObject>`` is the most insidious — it embeds arbitrary
      HTML inside the SVG namespace, including ``<script>``, and
      sanitisers that only strip ``<script>`` miss it.
    * **Event handlers** — any ``\\son<lower-letters>=`` attribute
      (``onload``, ``onclick``, ``onerror``, ``onmouseover``, and the
      long tail of HTML/SVG events). Generic regex catches the entire
      class without enumerating every event name.

    The framework REJECTS rather than SANITISES because half-cleaned
    SVG is a worse outcome than a denied upload — content sanitation
    of arbitrary XML is a known unsolved problem (see the long history
    of mXSS bypasses against DOMPurify, bleach, etc.). Projects that
    need to accept arbitrary SVG should run a vetted sanitiser on the
    bytes BEFORE calling :func:`save_upload`, or accept and serve the
    document with a defanged ``Content-Type: text/plain`` so the
    browser does not parse it.
    """
    head = content[:_SVG_SCAN_LIMIT]
    lower = head.lower()
    for tag in _SVG_FORBIDDEN_TAGS:
        if tag in lower:
            raise UploadError(
                f"SVG contains forbidden tag '{tag.decode()}' — refuses inline "
                'scripts and HTML embedding to prevent stored XSS. Sanitise '
                'server-side before upload, or serve with Content-Type: text/plain.'
            )
    if _SVG_EVENT_HANDLER_RE.search(head):
        raise UploadError(
            'SVG contains an on-* event handler attribute (e.g. onload, onclick) '
            '— would execute when rendered inline. Sanitise before upload.'
        )


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


def _stream_to_disk(source, file_path: str, upload_dir: str) -> None:
    """Synchronous mkdir + stream-copy — runs in a thread executor.

    Streams 64 KB chunks from ``source`` (a file-like positioned at
    byte 0) to ``file_path`` via ``shutil.copyfileobj`` so the full
    payload never sits in RAM — a 100-user / 10 MB upload burst uses
    ~6 MB of intermediate buffers instead of ~1 GB.
    """
    Path(upload_dir).mkdir(parents=True, exist_ok=True)
    with open(file_path, 'wb') as out:
        shutil.copyfileobj(source, out, length=64 * 1024)


async def _store_local(
    filename: str,
    source,
    upload_dir: str,
) -> tuple[str, str]:
    """Store a file on the local filesystem (streaming).

    Args:
        filename: Generated filename (e.g. ``'abc123.jpg'``).
        source: File-like object (positioned at 0) yielding the body.
            Typically a ``tempfile.SpooledTemporaryFile`` from the
            streaming buffer in :func:`save_upload`.
        upload_dir: Directory to save into.

    Returns:
        A tuple of ``(absolute_path, url)`` where url is
        ``/uploads/{filename}``.
    """
    file_path = os.path.join(upload_dir, filename)
    await asyncio.to_thread(_stream_to_disk, source, file_path, upload_dir)
    return file_path, f'/uploads/{filename}'


_DRIVERS: dict[str, Callable] = {
    'local': _store_local,
}


def register_storage_driver(name: str, handler: Callable) -> None:
    """Register a custom storage driver.

    The handler must be an async callable with signature::

        async def handler(filename: str, source, upload_dir: str) -> tuple[str, str]

    where ``source`` is a file-like object positioned at byte 0 (in
    practice a :class:`tempfile.SpooledTemporaryFile` produced by
    :func:`_spool_body`).  The handler MUST NOT close ``source`` —
    its lifetime is owned by :func:`save_upload`.  Stream from
    ``source`` via ``shutil.copyfileobj`` or ``aioboto3``'s
    ``upload_fileobj``; do NOT call ``source.read()`` unbounded
    because the source may be a multi-GB temp file on disk.

    .. note::

       The driver signature changed in 1.23 from ``(filename,
       content: bytes, upload_dir)`` to ``(filename, source,
       upload_dir)``.  Pre-1.23 drivers must update — replace any
       reference to ``content`` with ``source.read()`` (or, ideally,
       a streaming copy).  This change bounds framework RAM use to
       ~8 MB per upload regardless of payload size.

    Returns ``(path, url)``.
    """
    _DRIVERS[name] = handler


def get_storage_drivers() -> set[str]:
    """Return the names of all registered storage drivers."""
    return set(_DRIVERS)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


_READ_CHUNK_SIZE: int = 64 * 1024  # 64 KB
_SPOOL_RAM_LIMIT: int = 8 * 1024 * 1024  # past this, the spool rolls to disk
_MAGIC_HEAD_SIZE: int = 16  # bytes peeked from the spool for magic verification


async def _spool_body(file, max_size: int) -> tuple[tempfile.SpooledTemporaryFile, int]:
    """Stream an UploadFile body into a SpooledTemporaryFile with a hard size cap.

    Starlette's multipart parser already writes the body to a
    SpooledTemporaryFile during request parsing.  Pre-1.23 the
    framework then drained that spool into Python ``bytes`` via
    ``b''.join(chunks)`` — a 10 GB upload allocated ~20 GB of RAM
    (the chunk list plus the joined bytes) before the size check
    could reject it.  Reading into our own spool keeps RAM bounded
    to :data:`_SPOOL_RAM_LIMIT` regardless of payload size: the
    spool stays in RAM up to that threshold and rolls to disk past
    it.

    The size cap is enforced *during* streaming — the loop breaks as
    soon as the running total crosses ``max_size``, so a 10 GB
    request reads at most ``max_size + _READ_CHUNK_SIZE`` bytes
    before refusing.

    Returns the spool (rewound to byte 0) and the total byte count.
    Raises :class:`UploadError` if ``max_size`` is exceeded; the
    spool is closed before the exception propagates so its disk
    backing (if any) is reclaimed immediately.
    """
    spool = tempfile.SpooledTemporaryFile(max_size=_SPOOL_RAM_LIMIT)
    total = 0
    try:
        while True:
            chunk = await file.read(_READ_CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > max_size:
                raise UploadError(f'File size exceeds max ({max_size} bytes)')
            spool.write(chunk)
    except BaseException:
        spool.close()
        raise
    spool.seek(0)
    return spool, total


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
        allowed_types = _default_allowed_types()
    if max_size is None:
        max_size = config.get('UPLOAD_MAX_SIZE', 10 * 1024 * 1024)
    if upload_dir is None:
        upload_dir = config.get('UPLOAD_DIR', 'uploads')

    original_name = file.filename or 'unnamed'

    # Validate extension
    ext = _validate_extension(original_name, allowed_types)

    # Validate MIME type
    _validate_mime_type(getattr(file, 'content_type', None), ext)

    # Fast path: if the upload reports a size and it already exceeds the
    # limit, refuse before reading anything.
    declared_size = getattr(file, 'size', None)
    if isinstance(declared_size, int) and declared_size > max_size:
        raise UploadError(f'File size ({declared_size} bytes) exceeds max ({max_size} bytes)')

    # Stream the body into a SpooledTemporaryFile (RAM up to
    # _SPOOL_RAM_LIMIT, then disk).  Never hold the full payload in
    # RAM — this is the load-bearing change for MED-1 (RAM
    # exhaustion).  The spool's lifetime is owned by this function;
    # the driver receives it in its on-disk shape and must NOT close
    # it.
    spool, size = await _spool_body(file, max_size)
    try:
        if size == 0:
            raise UploadError('File is empty')

        # Magic-byte verification: peek the first bytes for the
        # signature check, then rewind so the driver still sees the
        # full body from byte 0.  16 bytes is enough for every
        # signature in _MAGIC_BYTES including the WebP RIFF+WEBP
        # check at offset 8-12.
        head = spool.read(_MAGIC_HEAD_SIZE)
        spool.seek(0)
        _validate_magic_bytes(head, ext)

        # SVG content scan. The magic-byte prefix above only proves
        # the file looks like XML — an attacker can prefix ``<?xml``
        # and still embed ``<script>`` further down. ``_validate_svg_content``
        # rejects the script / event-handler vectors that turn an SVG
        # into stored XSS when rendered inline. Cap the read at
        # ``_SVG_SCAN_LIMIT`` so a multi-MB SVG cannot become a CPU
        # DoS for the validator.
        if ext == 'svg':
            scan_buf = spool.read(_SVG_SCAN_LIMIT)
            spool.seek(0)
            _validate_svg_content(scan_buf)

        # Generate unique name and dispatch to driver
        filename = _generate_filename(ext)

        driver_name = driver or config.get('STORAGE_DRIVER', 'local')
        handler = _DRIVERS.get(driver_name)
        if handler is None:
            available = ', '.join(sorted(_DRIVERS))
            raise ValueError(f"Unknown storage driver '{driver_name}'. Available drivers: {available}")

        file_path, url = await handler(filename, spool, upload_dir)
    finally:
        spool.close()

    return UploadResult(
        filename=filename,
        path=file_path,
        url=url,
        size=size,
        original_name=original_name,
    )
