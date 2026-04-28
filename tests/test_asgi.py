"""Regression tests for asgi.py scaffolding — middleware ordering."""

from __future__ import annotations

from types import SimpleNamespace

from asgi import _build_middleware


def _settings(*, cors_origins: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        SECRET_KEY='test-secret',
        DEBUG=True,
        CORS_ORIGINS=cors_origins or [],
        CORS_ALLOW_METHODS=['GET', 'POST'],
        CORS_ALLOW_HEADERS=['*'],
        CORS_ALLOW_CREDENTIALS=False,
    )


def _names(stack) -> list[str]:
    return [m.cls.__name__ for m in stack]


def test_middleware_order_without_cors():
    stack = _build_middleware(_settings())
    assert _names(stack) == [
        'RequestIdMiddleware',
        'SecurityHeadersMiddleware',
        'SessionMiddleware',
        'CsrfMiddleware',
    ]


def test_middleware_order_with_cors_keeps_security_headers_outside_cors():
    # Regression: a previous bug used insert(1, ...) which placed CORS BEFORE
    # SecurityHeaders, so preflight responses skipped security headers.
    stack = _build_middleware(_settings(cors_origins=['https://example.com']))
    names = _names(stack)
    assert names == [
        'RequestIdMiddleware',
        'SecurityHeadersMiddleware',
        'CORSMiddleware',
        'SessionMiddleware',
        'CsrfMiddleware',
    ]
    assert names.index('SecurityHeadersMiddleware') < names.index('CORSMiddleware'), (
        'SecurityHeadersMiddleware must wrap CORSMiddleware so preflight responses receive security headers.'
    )
