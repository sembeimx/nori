"""Tests for core.http.upload."""
import os
import tempfile

import pytest

from core.http.upload import save_upload, UploadError


class FakeUploadFile:
    """Mimics Starlette's UploadFile for testing."""

    def __init__(self, filename='test.jpg', content_type='image/jpeg', content=b'\xff\xd8\xff'):
        self.filename = filename
        self.content_type = content_type
        self._content = content
        self.size = len(content)

    async def read(self):
        return self._content

    async def seek(self, pos):
        pass

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_save_upload_success():
    """Valid file saves correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = FakeUploadFile(filename='photo.jpg', content_type='image/jpeg', content=b'\xff\xd8\xff' * 10)
        result = await save_upload(f, allowed_types=['jpg', 'png'], max_size=1024, upload_dir=tmpdir)
        assert result.original_name == 'photo.jpg'
        assert result.filename.endswith('.jpg')
        assert result.size == 30
        assert os.path.exists(result.path)


@pytest.mark.asyncio
async def test_save_upload_invalid_extension():
    """Rejects files with disallowed extensions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = FakeUploadFile(filename='hack.exe', content_type='application/octet-stream')
        with pytest.raises(UploadError, match='not allowed'):
            await save_upload(f, allowed_types=['jpg', 'png'], upload_dir=tmpdir)


@pytest.mark.asyncio
async def test_save_upload_too_large():
    """Rejects files exceeding max size."""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = FakeUploadFile(filename='big.jpg', content_type='image/jpeg', content=b'x' * 2000)
        with pytest.raises(UploadError, match='exceeds'):
            await save_upload(f, allowed_types=['jpg'], max_size=1000, upload_dir=tmpdir)


@pytest.mark.asyncio
async def test_save_upload_mime_mismatch():
    """Rejects files where MIME type doesn't match extension."""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = FakeUploadFile(filename='image.png', content_type='image/jpeg', content=b'data')
        with pytest.raises(UploadError, match='MIME type'):
            await save_upload(f, allowed_types=['png'], upload_dir=tmpdir)


@pytest.mark.asyncio
async def test_save_upload_unique_names():
    """Two uploads of same file produce different filenames."""
    with tempfile.TemporaryDirectory() as tmpdir:
        f1 = FakeUploadFile(filename='a.jpg')
        f2 = FakeUploadFile(filename='a.jpg')
        r1 = await save_upload(f1, allowed_types=['jpg'], upload_dir=tmpdir)
        r2 = await save_upload(f2, allowed_types=['jpg'], upload_dir=tmpdir)
        assert r1.filename != r2.filename
