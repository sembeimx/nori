"""Tests for Request ID middleware."""

import asyncio
import logging

import pytest
from core.http.request_id import RequestIdMiddleware, get_request_id, request_id_var

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


# --- ContextVar propagation ---


def test_get_request_id_returns_none_outside_request():
    assert get_request_id() is None


@pytest.mark.asyncio
async def test_contextvar_set_during_request_and_reset_after():
    seen_inside: list[str | None] = []

    async def app(scope, receive, send):
        seen_inside.append(get_request_id())
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': b''})

    mw = RequestIdMiddleware(app)
    await mw(
        {'type': 'http', 'headers': [(b'x-request-id', b'trace-abc')]},
        lambda: {'type': 'http.request', 'body': b''},
        lambda msg: asyncio.sleep(0),
    )
    assert seen_inside == ['trace-abc']
    assert get_request_id() is None  # reset after the request finishes


@pytest.mark.asyncio
async def test_background_task_inherits_request_id():
    """asyncio.create_task copies the context, so background tasks see the request_id."""
    captured: dict = {}

    async def background_work() -> None:
        captured['from_background'] = get_request_id()

    async def app(scope, receive, send):
        # Spawn a task inside the handler — same pattern as core.audit / core.queue.
        task = asyncio.create_task(background_work())
        await task
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': b''})

    mw = RequestIdMiddleware(app)
    await mw(
        {'type': 'http', 'headers': [(b'x-request-id', b'trace-bg-7')]},
        lambda: {'type': 'http.request', 'body': b''},
        lambda msg: asyncio.sleep(0),
    )
    assert captured['from_background'] == 'trace-bg-7'


@pytest.mark.asyncio
async def test_log_filter_injects_request_id_into_records(caplog, monkeypatch):
    """Logs emitted under a request automatically carry record.request_id."""
    # core.logger sets propagate=False on 'nori', so caplog (rooted) only sees
    # records when propagation is temporarily re-enabled.
    monkeypatch.setattr(logging.getLogger('nori'), 'propagate', True)

    log = logging.getLogger('nori.test_request_id')

    token = request_id_var.set('trace-from-test')
    try:
        with caplog.at_level(logging.INFO, logger='nori.test_request_id'):
            log.info('hello from inside the request')
    finally:
        request_id_var.reset(token)

    matching = [r for r in caplog.records if r.message == 'hello from inside the request']
    assert matching, 'expected the test record to be captured'
    assert getattr(matching[0], 'request_id', None) == 'trace-from-test'


@pytest.mark.asyncio
async def test_log_filter_no_request_id_outside_request(caplog, monkeypatch):
    """Outside an HTTP context the filter does not inject a request_id."""
    monkeypatch.setattr(logging.getLogger('nori'), 'propagate', True)

    log = logging.getLogger('nori.test_request_id')

    with caplog.at_level(logging.INFO, logger='nori.test_request_id'):
        log.info('outside-of-request log line')

    matching = [r for r in caplog.records if r.message == 'outside-of-request log line']
    assert matching
    assert not hasattr(matching[0], 'request_id') or matching[0].request_id is None
