"""Tests for Request ID middleware."""
import pytest
from core.http.request_id import RequestIdMiddleware


# --- Unit tests ---

@pytest.mark.asyncio
async def test_generates_uuid():
    captured = {}

    async def app(scope, receive, send):
        captured['request_id'] = scope['state']['request_id']
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': b''})

    mw = RequestIdMiddleware(app)

    sent = []
    await mw(
        {'type': 'http', 'headers': []},
        lambda: {'type': 'http.request', 'body': b''},
        lambda msg: sent.append(msg) or __import__('asyncio').sleep(0),
    )

    assert len(captured['request_id']) == 36  # UUID4 format
    header_dict = dict(sent[0]['headers'])
    assert b'x-request-id' in header_dict


@pytest.mark.asyncio
async def test_propagates_incoming_header():
    captured = {}

    async def app(scope, receive, send):
        captured['request_id'] = scope['state']['request_id']
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': b''})

    mw = RequestIdMiddleware(app)

    sent = []
    await mw(
        {'type': 'http', 'headers': [(b'x-request-id', b'my-trace-123')]},
        lambda: {'type': 'http.request', 'body': b''},
        lambda msg: sent.append(msg) or __import__('asyncio').sleep(0),
    )

    assert captured['request_id'] == 'my-trace-123'


@pytest.mark.asyncio
async def test_skips_non_http():
    called = False

    async def app(scope, receive, send):
        nonlocal called
        called = True

    mw = RequestIdMiddleware(app)
    await mw({'type': 'websocket'}, None, None)
    assert called


# --- E2E tests ---

@pytest.mark.asyncio
async def test_response_has_x_request_id(client):
    resp = await client.get('/health')
    assert 'x-request-id' in resp.headers
    assert len(resp.headers['x-request-id']) == 36


@pytest.mark.asyncio
async def test_different_requests_get_different_ids(client):
    r1 = await client.get('/health')
    r2 = await client.get('/health')
    assert r1.headers['x-request-id'] != r2.headers['x-request-id']
