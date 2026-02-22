"""
File upload utilities.

    from core.http.upload import save_upload, UploadResult, UploadError

    result = await save_upload(
        file,
        allowed_types=['jpg', 'png', 'pdf'],
        max_size=5 * 1024 * 1024,  # 5 MB
    )
    # result.filename, result.path, result.url, result.size, result.original_name
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path

import settings

_MIME_MAP: dict[str, str] = {
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'png': 'image/png',
    'gif': 'image/gif',
    'pdf': 'application/pdf',
    'webp': 'image/webp',
    'svg': 'image/svg+xml',
}


class UploadError(Exception):
    """Raised when a file upload fails validation."""


@dataclass
class UploadResult:
    filename: str
    path: str
    url: str
    size: int
    original_name: str


def _validate_extension(filename: str, allowed_types: list[str]) -> str:
    """Validate and return file extension (lowercase, without dot)."""
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in allowed_types:
        raise UploadError(
            f"Extension '.{ext}' not allowed. Allowed: {', '.join(allowed_types)}"
        )
    return ext


def _validate_mime_type(content_type: str | None, ext: str) -> None:
    """Validate that MIME type matches expected type for the extension."""
    expected = _MIME_MAP.get(ext)
    if expected and content_type and content_type != expected:
        raise UploadError(
            f"MIME type '{content_type}' does not match extension '.{ext}' (expected '{expected}')"
        )


def _generate_filename(ext: str) -> str:
    """Generate a unique filename with UUID."""
    return f"{uuid.uuid4().hex}.{ext}"


async def save_upload(
    file,
    *,
    allowed_types: list[str] | None = None,
    max_size: int | None = None,
    upload_dir: str | None = None,
) -> UploadResult:
    """
    Validate and save an uploaded file.

    Args:
        file: Starlette UploadFile instance.
        allowed_types: List of allowed extensions (e.g. ['jpg', 'png']).
        max_size: Max file size in bytes.
        upload_dir: Directory to save into (default: settings.UPLOAD_DIR).

    Returns:
        UploadResult with file metadata.

    Raises:
        UploadError: If validation fails.
    """
    if allowed_types is None:
        allowed_types = list(_MIME_MAP.keys())
    if max_size is None:
        max_size = getattr(settings, 'UPLOAD_MAX_SIZE', 10 * 1024 * 1024)
    if upload_dir is None:
        upload_dir = getattr(settings, 'UPLOAD_DIR', os.path.join(settings._app_dir, 'uploads'))

    original_name = file.filename or 'unnamed'

    # Validate extension
    ext = _validate_extension(original_name, allowed_types)

    # Validate MIME type
    _validate_mime_type(getattr(file, 'content_type', None), ext)

    # Read content and validate size
    content = await file.read()
    if len(content) > max_size:
        raise UploadError(
            f"File size ({len(content)} bytes) exceeds max ({max_size} bytes)"
        )

    # Generate unique name and save
    filename = _generate_filename(ext)
    Path(upload_dir).mkdir(parents=True, exist_ok=True)
    file_path = os.path.join(upload_dir, filename)

    with open(file_path, 'wb') as f:
        f.write(content)

    return UploadResult(
        filename=filename,
        path=file_path,
        url=f"/uploads/{filename}",
        size=len(content),
        original_name=original_name,
    )
