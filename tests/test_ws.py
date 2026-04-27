"""Tests for WebSocket handlers."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../rootsystem/application')))

from asgi import app
from starlette.testclient import TestClient

client = TestClient(app)


def test_echo_receives_and_responds():
    """Echo handler responds with 'Echo: {message}'."""
    with client.websocket_connect('/ws/echo') as ws:
        ws.send_text('hello')
        data = ws.receive_text()
        assert data == 'Echo: hello'


def test_echo_multiple_messages():
    """Echo handler handles multiple messages in sequence."""
    with client.websocket_connect('/ws/echo') as ws:
        ws.send_text('first')
        assert ws.receive_text() == 'Echo: first'
        ws.send_text('second')
        assert ws.receive_text() == 'Echo: second'


def test_base_handler_accepts_connection():
    """WebSocket connection is accepted (doesn't error on connect)."""
    with client.websocket_connect('/ws/echo') as ws:
        ws.send_text('ping')
        resp = ws.receive_text()
        assert resp is not None
