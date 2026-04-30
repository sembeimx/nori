"""Tests for core.audit — audit logging utility."""

import asyncio

import pytest
from core.audit import audit, get_client_ip

# -- Fakes -------------------------------------------------------------------


class FakeClient:
    def __init__(self, host='127.0.0.1'):
        self.host = host


class FakeState:
    pass


class FakeSession(dict):
    pass


class FakeRequest:
    def __init__(self, *, ip='127.0.0.1', user_id=None, request_id=None, forwarded_for=None):
        self.client = FakeClient(ip) if ip else None
        self.session = FakeSession()
        if user_id is not None:
            self.session['user_id'] = user_id
        self.state = FakeState()
        if request_id is not None:
            self.state.request_id = request_id
        self._headers = {}
        if forwarded_for:
            self._headers['x-forwarded-for'] = forwarded_for

    @property
    def headers(self):
        return self._headers


# -- get_client_ip -----------------------------------------------------------


def test_get_client_ip_from_client():
    req = FakeRequest(ip='10.0.0.1')
    assert get_client_ip(req) == '10.0.0.1'


def test_get_client_ip_from_forwarded_for(monkeypatch):
    import settings

    monkeypatch.setattr(settings, 'TRUSTED_PROXIES', ['10.0.0.1'])
    req = FakeRequest(ip='10.0.0.1', forwarded_for='203.0.113.5, 10.0.0.1')
    assert get_client_ip(req) == '203.0.113.5'


def test_get_client_ip_ignores_forwarded_for_from_untrusted():
    """X-Forwarded-For is ignored when direct IP is not in TRUSTED_PROXIES."""
    req = FakeRequest(ip='10.0.0.1', forwarded_for='203.0.113.5, 10.0.0.1')
    assert get_client_ip(req) == '10.0.0.1'


def test_get_client_ip_no_client():
    req = FakeRequest(ip=None)
    assert get_client_ip(req) is None


def test_get_client_ip_rejects_spoofed_leftmost(monkeypatch):
    """An attacker can inject any value as the leftmost X-Forwarded-For
    entry; the proxy appends the real source to the right but does not
    rewrite the spoofed prefix. Right-to-left walk discards the spoof.

    Scenario: attacker at 5.5.5.5 sends ``X-Forwarded-For: 1.2.3.4`` to
    the proxy at 10.0.0.1. The proxy appends 5.5.5.5 to the chain. The
    function must return 5.5.5.5 (the real source), not 1.2.3.4.
    """
    import settings

    monkeypatch.setattr(settings, 'TRUSTED_PROXIES', ['10.0.0.1'])
    req = FakeRequest(ip='10.0.0.1', forwarded_for='1.2.3.4, 5.5.5.5')
    assert get_client_ip(req) == '5.5.5.5'


def test_get_client_ip_walks_multi_proxy_chain(monkeypatch):
    """With a CDN → ALB → app chain, both proxies are in TRUSTED_PROXIES
    and each appends its source. The first non-trusted entry from the
    right is the real client even when an attacker prepends a spoof."""
    import settings

    monkeypatch.setattr(settings, 'TRUSTED_PROXIES', ['10.0.0.1', '1.1.1.1'])
    # Attacker (5.5.5.5) injects 'spoof' → CDN appends 5.5.5.5 → ALB appends 1.1.1.1
    req = FakeRequest(
        ip='10.0.0.1',
        forwarded_for='spoof, 5.5.5.5, 1.1.1.1',
    )
    assert get_client_ip(req) == '5.5.5.5'


def test_get_client_ip_falls_back_when_chain_is_all_trusted(monkeypatch):
    """If every entry in X-Forwarded-For is a trusted proxy (e.g. internal
    health-check between proxies), no real client identity is available —
    fall back to the direct connection IP rather than returning a proxy
    address."""
    import settings

    monkeypatch.setattr(settings, 'TRUSTED_PROXIES', ['10.0.0.1', '1.1.1.1'])
    req = FakeRequest(ip='10.0.0.1', forwarded_for='10.0.0.1, 1.1.1.1')
    assert get_client_ip(req) == '10.0.0.1'


def test_get_client_ip_strips_whitespace_in_chain(monkeypatch):
    """Browsers and proxies emit varying whitespace around commas; the
    parser must strip so the trusted-list lookup is exact."""
    import settings

    monkeypatch.setattr(settings, 'TRUSTED_PROXIES', ['10.0.0.1'])
    req = FakeRequest(ip='10.0.0.1', forwarded_for='  203.0.113.5  ,   10.0.0.1  ')
    assert get_client_ip(req) == '203.0.113.5'


# -- audit() -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_returns_asyncio_task():
    req = FakeRequest(user_id=1)
    task = audit(req, 'create', model_name='Article', record_id=42)
    assert isinstance(task, asyncio.Task)
    await task


@pytest.mark.asyncio
async def test_audit_writes_to_database():
    req = FakeRequest(user_id=5, ip='192.168.1.1', request_id='abc-123')
    task = audit(
        req,
        'update',
        model_name='Article',
        record_id=7,
        changes={'title': {'before': 'Old', 'after': 'New'}},
    )
    await task

    from models.framework.audit_log import AuditLog

    log = await AuditLog.filter(request_id='abc-123').first()
    assert log is not None
    assert log.user_id == 5
    assert log.action == 'update'
    assert log.model_name == 'Article'
    assert log.record_id == '7'
    assert log.ip_address == '192.168.1.1'
    assert log.changes['title']['after'] == 'New'


@pytest.mark.asyncio
async def test_audit_resolves_user_from_session():
    req = FakeRequest(user_id=99)
    task = audit(req, 'login')
    await task

    from models.framework.audit_log import AuditLog

    log = await AuditLog.filter(user_id=99, action='login').first()
    assert log is not None


@pytest.mark.asyncio
async def test_audit_explicit_user_id_overrides_session():
    req = FakeRequest(user_id=1)
    task = audit(req, 'delete', user_id=42)
    await task

    from models.framework.audit_log import AuditLog

    log = await AuditLog.filter(user_id=42, action='delete').first()
    assert log is not None


@pytest.mark.asyncio
async def test_audit_nullable_fields():
    req = FakeRequest()
    task = audit(req, 'custom_action')
    await task

    from models.framework.audit_log import AuditLog

    log = await AuditLog.filter(action='custom_action').first()
    assert log is not None
    assert log.user_id is None
    assert log.model_name is None
    assert log.record_id is None
    assert log.changes is None


def test_get_client_ip_trusted_proxy_empty_forwarded(monkeypatch):
    """Empty X-Forwarded-For from trusted proxy falls back to direct IP."""
    import settings

    monkeypatch.setattr(settings, 'TRUSTED_PROXIES', ['10.0.0.1'])
    req = FakeRequest(ip='10.0.0.1', forwarded_for='')
    assert get_client_ip(req) == '10.0.0.1'


@pytest.mark.asyncio
async def test_audit_casts_string_user_id():
    """user_id stored as string in session is cast to int."""
    req = FakeRequest(user_id='42')
    task = audit(req, 'cast_test')
    await task

    from models.framework.audit_log import AuditLog

    log = await AuditLog.filter(action='cast_test').first()
    assert log is not None
    assert log.user_id == 42
    assert isinstance(log.user_id, int)


@pytest.mark.asyncio
async def test_audit_handles_db_failure(monkeypatch, caplog):
    """Exception in _write background task is logged and doesn't crash."""
    import logging

    from models.framework.audit_log import AuditLog

    async def _fail(*args, **kwargs):
        raise Exception('DB is down')

    monkeypatch.setattr(AuditLog, 'create', _fail)

    # core.logger sets propagate=False on the 'nori' root, so caplog (which
    # listens on the actual root) only sees our 'nori.audit' records when
    # propagation is temporarily re-enabled.
    monkeypatch.setattr(logging.getLogger('nori'), 'propagate', True)

    req = FakeRequest()
    with caplog.at_level(logging.ERROR, logger='nori.audit'):
        task = audit(req, 'fail_test')
        await task  # background task swallows the exception

    assert any('Failed to write audit log entry' in r.message for r in caplog.records)


def test_audit_no_loop_warning(monkeypatch):
    """Calling audit() without a running loop logs a warning and returns None."""
    # Mock asyncio.get_running_loop to raise RuntimeError
    import asyncio

    def _no_loop():
        raise RuntimeError('no loop')

    monkeypatch.setattr(asyncio, 'get_running_loop', _no_loop)

    req = FakeRequest()
    # Should not raise exception
    task = audit(req, 'no_loop_test')
    assert task is None
