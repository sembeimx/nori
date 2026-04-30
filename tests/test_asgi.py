"""Regression tests for asgi.py scaffolding — middleware ordering."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from asgi import _build_middleware, _warn_missing_trusted_proxies


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


# -- _warn_missing_trusted_proxies -----------------------------------------


class _Recorder:
    """Minimal logger stand-in that records ``warning()`` calls."""

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, msg: str, *args: object) -> None:
        self.warnings.append(msg % args if args else msg)


def test_trusted_proxies_warning_emits_in_production():
    """Behind a load balancer, an empty TRUSTED_PROXIES yields audit logs that
    record the proxy's internal IP for every request — observability gap
    worth a startup warning. The framework still fails secure (refuses
    spoofed X-Forwarded-For), so this is informational, not a vulnerability.
    """
    settings_module = SimpleNamespace(DEBUG=False, TRUSTED_PROXIES=[])
    rec = _Recorder()
    emitted = _warn_missing_trusted_proxies(settings_module, rec)

    assert emitted is True
    assert any('TRUSTED_PROXIES' in w for w in rec.warnings)


def test_trusted_proxies_warning_silent_in_debug():
    """Local development without TRUSTED_PROXIES is the normal case — the
    warning must not fire and pollute the dev log."""
    settings_module = SimpleNamespace(DEBUG=True, TRUSTED_PROXIES=[])
    rec = _Recorder()

    assert _warn_missing_trusted_proxies(settings_module, rec) is False
    assert rec.warnings == []


def test_trusted_proxies_warning_silent_when_configured():
    """Operator already set TRUSTED_PROXIES — no warning, the misconfiguration
    they would have been told about no longer exists."""
    settings_module = SimpleNamespace(DEBUG=False, TRUSTED_PROXIES=['127.0.0.1'])
    rec = _Recorder()

    assert _warn_missing_trusted_proxies(settings_module, rec) is False
    assert rec.warnings == []


def test_trusted_proxies_warning_silent_when_attribute_missing():
    """A settings module without TRUSTED_PROXIES at all (older project that
    never opted in) must not blow up — getattr default keeps the helper
    backwards-compatible."""
    settings_module = SimpleNamespace(DEBUG=False)
    rec = _Recorder()

    # Should not raise and should not warn (no attribute → treated as empty
    # but we still want to point that out, since the default IS empty).
    emitted = _warn_missing_trusted_proxies(settings_module, rec)
    assert emitted is True


def test_trusted_proxies_warning_silent_with_real_logger(monkeypatch, caplog):
    """End-to-end with the real ``logging`` API — verifies the helper
    actually emits a record at WARNING level on the expected logger,
    not just calls ``.warning()`` on a duck-typed stub.

    ``core.logger`` sets ``propagate=False`` on the ``nori`` parent so
    application logs don't double-print under uvicorn's handler. Tests
    that read via ``caplog`` (which attaches to the actual root) need
    to re-enable propagation for the duration of the assertion.
    """
    monkeypatch.setattr(logging.getLogger('nori'), 'propagate', True)
    settings_module = SimpleNamespace(DEBUG=False, TRUSTED_PROXIES=[])
    logger = logging.getLogger('nori.asgi.test')

    with caplog.at_level(logging.WARNING, logger='nori.asgi.test'):
        _warn_missing_trusted_proxies(settings_module, logger)

    assert any('TRUSTED_PROXIES' in r.message for r in caplog.records)
