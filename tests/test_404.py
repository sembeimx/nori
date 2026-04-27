"""Tests for the 404 not_found handler."""
import pytest
from asgi import not_found


class FakeHeaders:
    def __init__(self, accept='text/html'):
        self._accept = accept

    def get(self, key, default=''):
        if key.lower() == 'accept':
            return self._accept
        return default


class FakeRequest:
    def __init__(self, accept='text/html'):
        self.headers = FakeHeaders(accept)
        self.session = {}
        # Starlette TemplateResponse needs these
        self._scope = {'type': 'http'}

    @property
    def scope(self):
        return self._scope


@pytest.mark.asyncio
async def test_not_found_json():
    """JSON accept header returns JSON 404."""
    req = FakeRequest(accept='application/json')
    resp = await not_found(req, Exception('test'))
    assert resp.status_code == 404
    assert resp.body == b'{"error":"Not Found"}'


@pytest.mark.asyncio
async def test_not_found_html():
    """HTML accept header returns template 404."""
    req = FakeRequest(accept='text/html')
    resp = await not_found(req, Exception('test'))
    assert resp.status_code == 404
    assert b'404' in resp.body
