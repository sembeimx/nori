"""Tests for core.http.upload."""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../rootsystem/application')))

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


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_save_upload_success():
    """Valid file saves correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = FakeUploadFile(filename='photo.jpg', content_type='image/jpeg', content=b'\xff\xd8\xff' * 10)
        result = _run(save_upload(f, allowed_types=['jpg', 'png'], max_size=1024, upload_dir=tmpdir))
        assert result.original_name == 'photo.jpg'
        assert result.filename.endswith('.jpg')
        assert result.size == 30
        assert os.path.exists(result.path)


def test_save_upload_invalid_extension():
    """Rejects files with disallowed extensions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = FakeUploadFile(filename='hack.exe', content_type='application/octet-stream')
        try:
            _run(save_upload(f, allowed_types=['jpg', 'png'], upload_dir=tmpdir))
            assert False, 'Should have raised UploadError'
        except UploadError as e:
            assert 'not allowed' in str(e)


def test_save_upload_too_large():
    """Rejects files exceeding max size."""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = FakeUploadFile(filename='big.jpg', content_type='image/jpeg', content=b'x' * 2000)
        try:
            _run(save_upload(f, allowed_types=['jpg'], max_size=1000, upload_dir=tmpdir))
            assert False, 'Should have raised UploadError'
        except UploadError as e:
            assert 'exceeds' in str(e)


def test_save_upload_mime_mismatch():
    """Rejects files where MIME type doesn't match extension."""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = FakeUploadFile(filename='image.png', content_type='image/jpeg', content=b'data')
        try:
            _run(save_upload(f, allowed_types=['png'], upload_dir=tmpdir))
            assert False, 'Should have raised UploadError'
        except UploadError as e:
            assert 'MIME type' in str(e)


def test_save_upload_unique_names():
    """Two uploads of same file produce different filenames."""
    with tempfile.TemporaryDirectory() as tmpdir:
        f1 = FakeUploadFile(filename='a.jpg')
        f2 = FakeUploadFile(filename='a.jpg')
        r1 = _run(save_upload(f1, allowed_types=['jpg'], upload_dir=tmpdir))
        r2 = _run(save_upload(f2, allowed_types=['jpg'], upload_dir=tmpdir))
        assert r1.filename != r2.filename
