"""Tests for the routes:list CLI command."""
from __future__ import annotations

import subprocess
import sys


def test_routes_list_shows_registered_routes():
    """routes:list should display the routes from routes.py."""
    result = subprocess.run(
        [sys.executable, 'nori.py', 'routes:list'],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    output = result.stdout
    # Should contain the header
    assert 'Path' in output
    assert 'Methods' in output
    assert 'Name' in output
    # Should contain the known routes from routes.py
    assert '/health' in output
    assert 'health.check' in output
    assert 'GET' in output
    assert 'page.home' in output
    # WebSocket route
    assert '/ws/echo' in output
    assert 'WS' in output
    assert 'ws.echo' in output
    # Should show the count
    assert 'route(s) registered' in output
