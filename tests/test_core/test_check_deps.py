"""Tests for the check:deps CLI command."""

from __future__ import annotations

import os
import subprocess
import sys


def test_check_deps_passes_with_default_config():
    """Default settings (sqlite + memory cache + memory throttle) should all pass."""
    result = subprocess.run(
        [sys.executable, 'nori.py', 'check:deps'],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    output = result.stdout
    assert '✓ Database' in output
    assert '✓ Cache' in output
    assert '✓ Throttle' in output
    assert 'All 3 dependency check(s) passed' in output


def test_check_deps_fails_when_redis_cache_unreachable():
    """When CACHE_BACKEND=redis but REDIS_URL is wrong, exit 1 with a clear failure line."""
    env = os.environ.copy()
    env['CACHE_BACKEND'] = 'redis'
    env['REDIS_URL'] = 'redis://localhost:9'  # unreachable port

    result = subprocess.run(
        [sys.executable, 'nori.py', 'check:deps'],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    output = result.stdout
    assert '✗ Cache' in output
    assert 'dependency check(s) failed' in output
