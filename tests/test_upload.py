"""Tests for core.http.upload — file validation and multi-driver storage.

Covers:
- Extension validation (allowed / disallowed)
- MIME type validation (match / mismatch)
- Magic byte content verification (real file signatures)
- File size validation (within / exceeds limit)
- Unique filename generation
- Local storage driver (_store_local)
- Driver dispatch (local, custom, unknown)
- Driver registration and introspection
- Edge case: file without filename
"""

import os
import tempfile
from unittest.mock import AsyncMock, patch

import core.http.upload as upload_module
import pytest
from core.http.upload import (
    _DRIVERS,
    UploadError,
    _store_local,
    _validate_magic_bytes,
    get_storage_drivers,
    register_storage_driver,
    save_upload,
)


class FakeUploadFile:
    """Mimics Starlette's UploadFile for testing.

    Args:
        filename: Original filename from the client.
        content_type: MIME type reported by the client.
        content: Raw file bytes.
    """

    def __init__(self, filename='test.jpg', content_type='image/jpeg', content=b'\xff\xd8\xff'):
        self.filename = filename
        self.content_type = content_type
        self._content = content
        self.size = len(content)
        self._pos = 0

    async def read(self, size=-1):
        if size is None or size < 0:
            data = self._content[self._pos:]
            self._pos = len(self._content)
            return data
        data = self._content[self._pos:self._pos + size]
        self._pos += len(data)
        return data

    async def seek(self, pos):
        self._pos = pos

    async def close(self):
        pass


@pytest.fixture(autouse=True)
def _cleanup_drivers():
    """Remove any test drivers registered during a test."""
    yield
    _DRIVERS.pop('test_custom', None)
    _DRIVERS.pop('test_reg', None)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_save_upload_success():
    """Valid file saves correctly and returns expected metadata."""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = FakeUploadFile(filename='photo.jpg', content_type='image/jpeg', content=b'\xff\xd8\xff' * 10)
        result = await save_upload(f, allowed_types=['jpg', 'png'], max_size=1024, upload_dir=tmpdir)
        assert result.original_name == 'photo.jpg'
        assert result.filename.endswith('.jpg')
        assert result.size == 30
        assert os.path.exists(result.path)


@pytest.mark.anyio
async def test_save_upload_invalid_extension():
    """Files with disallowed extensions are rejected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = FakeUploadFile(filename='hack.exe', content_type='application/octet-stream')
        with pytest.raises(UploadError, match='not allowed'):
            await save_upload(f, allowed_types=['jpg', 'png'], upload_dir=tmpdir)


@pytest.mark.anyio
async def test_save_upload_too_large():
    """Files exceeding max_size are rejected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = FakeUploadFile(filename='big.jpg', content_type='image/jpeg', content=b'x' * 2000)
        with pytest.raises(UploadError, match='exceeds'):
            await save_upload(f, allowed_types=['jpg'], max_size=1000, upload_dir=tmpdir)


@pytest.mark.anyio
async def test_save_upload_aborts_streaming_before_full_buffer():
    """Reading aborts as soon as the running total exceeds max_size, not after the full body."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # 5MB of 'x' — the streaming reader must reject before buffering the
        # whole thing. Track how many bytes we ever held in memory at once.
        f = FakeUploadFile(filename='big.jpg', content_type='image/jpeg', content=b'x' * (5 * 1024 * 1024))
        with pytest.raises(UploadError, match='exceeds'):
            await save_upload(f, allowed_types=['jpg'], max_size=1024, upload_dir=tmpdir)
        # FakeUploadFile.read returns slices, so a successful early-abort
        # leaves _pos somewhere just past max_size, not at the end.
        assert f._pos <= 1024 + 64 * 1024, f'streamed past the limit: pos={f._pos}'


@pytest.mark.anyio
async def test_save_upload_rejects_via_declared_size_fast_path():
    """If UploadFile.size already exceeds max_size, reject without reading at all."""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = FakeUploadFile(filename='huge.jpg', content_type='image/jpeg', content=b'\xff\xd8\xff')
        f.size = 10 * 1024 * 1024 * 1024  # claims 10GB without actually allocating
        with pytest.raises(UploadError, match='exceeds'):
            await save_upload(f, allowed_types=['jpg'], max_size=1024, upload_dir=tmpdir)
        # We refused before any read happened.
        assert f._pos == 0


@pytest.mark.anyio
async def test_save_upload_mime_mismatch():
    """Files where MIME type doesn't match the extension are rejected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = FakeUploadFile(filename='image.png', content_type='image/jpeg', content=b'data')
        with pytest.raises(UploadError, match='MIME type'):
            await save_upload(f, allowed_types=['png'], upload_dir=tmpdir)


@pytest.mark.anyio
async def test_save_upload_unique_names():
    """Two uploads of the same file produce different filenames."""
    with tempfile.TemporaryDirectory() as tmpdir:
        f1 = FakeUploadFile(filename='a.jpg')
        f2 = FakeUploadFile(filename='a.jpg')
        r1 = await save_upload(f1, allowed_types=['jpg'], upload_dir=tmpdir)
        r2 = await save_upload(f2, allowed_types=['jpg'], upload_dir=tmpdir)
        assert r1.filename != r2.filename


@pytest.mark.anyio
async def test_save_upload_no_filename():
    """A file with no filename falls back to 'unnamed'."""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = FakeUploadFile(filename=None, content_type='image/jpeg')
        # 'unnamed' has no extension, so it won't match any allowed type
        with pytest.raises(UploadError, match='not allowed'):
            await save_upload(f, allowed_types=['jpg'], upload_dir=tmpdir)


# ---------------------------------------------------------------------------
# Magic byte verification
# ---------------------------------------------------------------------------


def test_magic_bytes_valid_jpeg():
    """Valid JPEG magic bytes pass verification."""
    _validate_magic_bytes(b'\xff\xd8\xff\xe0' + b'\x00' * 100, 'jpg')


def test_magic_bytes_valid_png():
    """Valid PNG magic bytes pass verification."""
    _validate_magic_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 100, 'png')


def test_magic_bytes_valid_gif87a():
    """GIF87a signature passes verification."""
    _validate_magic_bytes(b'GIF87a' + b'\x00' * 100, 'gif')


def test_magic_bytes_valid_gif89a():
    """GIF89a signature passes verification."""
    _validate_magic_bytes(b'GIF89a' + b'\x00' * 100, 'gif')


def test_magic_bytes_valid_pdf():
    """Valid PDF magic bytes pass verification."""
    _validate_magic_bytes(b'%PDF-1.4' + b'\x00' * 100, 'pdf')


def test_magic_bytes_valid_webp():
    """Valid WebP (RIFF) magic bytes pass verification."""
    _validate_magic_bytes(b'RIFF\x00\x00\x00\x00WEBP' + b'\x00' * 100, 'webp')


def test_magic_bytes_fake_jpeg_rejected():
    """A file claiming to be JPEG but with wrong content is rejected."""
    with pytest.raises(UploadError, match='magic byte'):
        _validate_magic_bytes(b'this is not a jpeg', 'jpg')


def test_magic_bytes_fake_png_rejected():
    """A file claiming to be PNG but with JPEG content is rejected."""
    with pytest.raises(UploadError, match='magic byte'):
        _validate_magic_bytes(b'\xff\xd8\xff', 'png')


def test_magic_bytes_unknown_extension_skipped():
    """Extensions without known magic bytes are skipped gracefully."""
    _validate_magic_bytes(b'anything', 'svg')
    _validate_magic_bytes(b'anything', 'csv')
    _validate_magic_bytes(b'anything', 'txt')


@pytest.mark.anyio
async def test_save_upload_rejects_disguised_file():
    """A .jpg with non-JPEG content is rejected by magic byte check."""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = FakeUploadFile(
            filename='malware.jpg',
            content_type='image/jpeg',
            content=b'MZ\x90\x00' + b'\x00' * 100,  # PE executable header
        )
        with pytest.raises(UploadError, match='magic byte'):
            await save_upload(f, allowed_types=['jpg'], upload_dir=tmpdir)


# ---------------------------------------------------------------------------
# _store_local
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_store_local():
    """Local driver writes file to disk and returns (path, url)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path, url = await _store_local('abc123.jpg', b'data', tmpdir)
        assert os.path.exists(path)
        assert url == '/uploads/abc123.jpg'
        with open(path, 'rb') as f:
            assert f.read() == b'data'


# ---------------------------------------------------------------------------
# Driver dispatch
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_save_upload_dispatches_to_local():
    """Default driver dispatches to the local handler."""
    mock_local = AsyncMock(return_value=('/tmp/file.jpg', '/uploads/file.jpg'))
    _cfg = {'STORAGE_DRIVER': 'local', 'UPLOAD_MAX_SIZE': 10 * 1024 * 1024, 'UPLOAD_DIR': '/tmp'}
    with patch.dict(_DRIVERS, {'local': mock_local}), patch.object(upload_module, 'config') as mock_config:
        mock_config.get = lambda k, d=None: _cfg.get(k, d)
        f = FakeUploadFile(filename='photo.jpg', content_type='image/jpeg')
        result = await save_upload(f, allowed_types=['jpg'])
        mock_local.assert_called_once()
        assert result.url == '/uploads/file.jpg'


@pytest.mark.anyio
async def test_save_upload_driver_override():
    """Per-call driver= overrides settings.STORAGE_DRIVER."""
    mock_custom = AsyncMock(return_value=('key/file.jpg', 'https://cdn.example.com/file.jpg'))
    register_storage_driver('test_custom', mock_custom)

    with tempfile.TemporaryDirectory() as tmpdir:
        f = FakeUploadFile(filename='photo.jpg', content_type='image/jpeg')
        result = await save_upload(f, allowed_types=['jpg'], upload_dir=tmpdir, driver='test_custom')
        mock_custom.assert_called_once()
        assert result.url == 'https://cdn.example.com/file.jpg'


@pytest.mark.anyio
async def test_save_upload_unknown_driver():
    """Unknown driver raises ValueError with the driver name."""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = FakeUploadFile(filename='photo.jpg', content_type='image/jpeg')
        with pytest.raises(ValueError, match="Unknown storage driver 'nonexistent'"):
            await save_upload(f, allowed_types=['jpg'], upload_dir=tmpdir, driver='nonexistent')


# ---------------------------------------------------------------------------
# register_storage_driver / get_storage_drivers
# ---------------------------------------------------------------------------


def test_register_storage_driver():
    """A custom driver appears in the registry after registration."""
    mock = AsyncMock()
    register_storage_driver('test_reg', mock)
    assert 'test_reg' in get_storage_drivers()


def test_get_storage_drivers():
    """Built-in local driver is always present."""
    drivers = get_storage_drivers()
    assert 'local' in drivers


# ---------------------------------------------------------------------------
# Edge cases for recent fixes
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_save_upload_empty_file_rejected():
    """Empty files (0 bytes) are rejected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = FakeUploadFile(filename='empty.jpg', content_type='image/jpeg', content=b'')
        with pytest.raises(UploadError, match='empty'):
            await save_upload(f, allowed_types=['jpg'], upload_dir=tmpdir)


@pytest.mark.anyio
async def test_save_upload_mime_with_charset_accepted():
    """MIME type with charset parameter should not cause false rejection."""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = FakeUploadFile(filename='photo.jpg', content_type='image/jpeg; charset=utf-8', content=b'\xff\xd8\xff' * 10)
        result = await save_upload(f, allowed_types=['jpg'], upload_dir=tmpdir)
        assert result.original_name == 'photo.jpg'


def test_magic_bytes_webp_rejects_non_webp_riff():
    """A RIFF file that is not WebP (e.g. WAV) is rejected for .webp extension."""
    wav_header = b'RIFF\x00\x00\x00\x00WAVE' + b'\x00' * 100
    with pytest.raises(UploadError, match='not WebP'):
        _validate_magic_bytes(wav_header, 'webp')


def test_magic_bytes_webp_too_short():
    """A file too short for RIFF+WEBP check passes the RIFF prefix but fails WEBP."""
    short = b'RIFF\x00\x00'
    # Only 6 bytes, can't check offset 8-12, but starts with RIFF so passes magic
    # bytes. The WebP extra check requires len >= 12, so short files skip it.
    _validate_magic_bytes(short, 'webp')  # should not raise
