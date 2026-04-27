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


@pytest.mark.asyncio
async def test_health_returns_503_on_db_error(client):
    """When DB is unreachable, health should return 503 with degraded status."""
    mock_conn = AsyncMock()
    mock_conn.execute_query = AsyncMock(side_effect=Exception("Connection refused"))

    with patch('tortoise.Tortoise.get_connection', return_value=mock_conn):
        resp = await client.get('/health')

    assert resp.status_code == 503
    body = resp.json()
    assert body['status'] == 'degraded'
    assert body['db'] == 'error'
