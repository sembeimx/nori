"""Tests for /health endpoint."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_health_returns_ok(client):
    resp = await client.get('/health')
    assert resp.status_code == 200
    body = resp.json()
    assert body['status'] == 'ok'
    assert body['db'] == 'ok'
    assert body['cache'] == 'ok'
    assert body['throttle'] == 'ok'


@pytest.mark.asyncio
async def test_health_returns_503_on_db_error(client):
    """When DB is unreachable, health should return 503 with degraded status."""
    mock_conn = AsyncMock()
    mock_conn.execute_query = AsyncMock(side_effect=Exception('Connection refused'))

    with patch('tortoise.Tortoise.get_connection', return_value=mock_conn):
        resp = await client.get('/health')

    assert resp.status_code == 503
    body = resp.json()
    assert body['status'] == 'degraded'
    assert body['db'] == 'error'


@pytest.mark.asyncio
async def test_health_returns_503_on_cache_error(client):
    """When the cache backend's verify() raises, health should return 503."""
    from core.cache import get_backend as get_cache_backend

    backend = get_cache_backend()
    with patch.object(backend, 'verify', AsyncMock(side_effect=RuntimeError('Redis down'))):
        resp = await client.get('/health')

    assert resp.status_code == 503
    body = resp.json()
    assert body['status'] == 'degraded'
    assert body['cache'] == 'error'


@pytest.mark.asyncio
async def test_health_returns_503_on_throttle_error(client):
    """When the throttle backend's verify() raises, health should return 503."""
    from core.http.throttle_backends import get_backend as get_throttle_backend

    backend = get_throttle_backend()
    with patch.object(backend, 'verify', AsyncMock(side_effect=RuntimeError('Redis down'))):
        resp = await client.get('/health')

    assert resp.status_code == 503
    body = resp.json()
    assert body['status'] == 'degraded'
    assert body['throttle'] == 'error'
