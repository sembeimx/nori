"""Tests for core.lifecycle — service-shutdown registry."""

from __future__ import annotations

import asyncio
import logging

import pytest
from core.lifecycle import (
    _reset_for_tests,
    _shutdown_handlers,
    register_shutdown,
    run_shutdown_handlers,
)


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Each test gets a clean registry. Without this, side-effects from
    one case (or from any other test that imports a service module)
    leak into the next.
    """
    _reset_for_tests()
    yield
    _reset_for_tests()


# ---------------------------------------------------------------------------
# register_shutdown
# ---------------------------------------------------------------------------


def test_register_shutdown_appends_one_entry():
    async def h() -> None: ...

    register_shutdown('svc', h)

    assert len(_shutdown_handlers) == 1
    assert _shutdown_handlers[0] == ('svc', h)


def test_register_shutdown_is_idempotent_for_same_handler():
    """A re-imported service driver (hot-reload, ``services.X.register()``
    called twice from different start-up paths) must not stack duplicate
    entries that all close the same — possibly already-replaced — client.
    """

    async def h() -> None: ...

    register_shutdown('svc', h)
    register_shutdown('svc', h)
    register_shutdown('svc', h)

    assert len(_shutdown_handlers) == 1


def test_register_shutdown_allows_distinct_handlers_under_same_name():
    """The name field is informational; identity is by handler object.
    Two genuinely different handlers under the same name both register —
    operators see the same name in logs but each ``aclose`` runs."""

    async def h1() -> None: ...

    async def h2() -> None: ...

    register_shutdown('svc', h1)
    register_shutdown('svc', h2)

    assert len(_shutdown_handlers) == 2


# ---------------------------------------------------------------------------
# run_shutdown_handlers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_shutdown_handlers_invokes_each_in_order():
    """Sequential invocation in registration order — gives operators a
    deterministic shutdown trace and means a stuck handler is recorded
    before the rest run."""
    order: list[str] = []

    async def h_first() -> None:
        order.append('first')

    async def h_second() -> None:
        order.append('second')

    async def h_third() -> None:
        order.append('third')

    register_shutdown('first', h_first)
    register_shutdown('second', h_second)
    register_shutdown('third', h_third)

    await run_shutdown_handlers()

    assert order == ['first', 'second', 'third']


@pytest.mark.asyncio
async def test_run_shutdown_handlers_returns_immediately_when_empty():
    """No-op fast path. The lifespan calls ``run_shutdown_handlers``
    unconditionally; a project that didn't activate any service driver
    must not pay anything for the call."""
    assert len(_shutdown_handlers) == 0
    await run_shutdown_handlers(per_handler_timeout=0.01)


@pytest.mark.asyncio
async def test_run_shutdown_handlers_swallows_per_handler_errors(monkeypatch, caplog):
    """A handler that raises must NOT prevent later handlers from
    running. Pre-fix the lifespan would propagate the exception and
    skip the remaining ``aclose`` calls — so an S3 client that already
    crashed could prevent a healthy GCS / mail / search client from
    being closed.
    """
    monkeypatch.setattr(logging.getLogger('nori'), 'propagate', True)

    ran: list[str] = []

    async def healthy_first() -> None:
        ran.append('first')

    async def crashing() -> None:
        raise RuntimeError('peer reset')

    async def healthy_third() -> None:
        ran.append('third')

    register_shutdown('first', healthy_first)
    register_shutdown('crashing', crashing)
    register_shutdown('third', healthy_third)

    with caplog.at_level(logging.ERROR, logger='nori.lifecycle'):
        await run_shutdown_handlers()

    assert ran == ['first', 'third'], (
        'a crashing handler dropped a later healthy handler — shutdown '
        'must be best-effort across all registered services'
    )
    assert any('crashing' in r.message for r in caplog.records), 'failing handler must be logged at ERROR with its name'


@pytest.mark.asyncio
async def test_run_shutdown_handlers_warns_on_per_handler_timeout(monkeypatch, caplog):
    """A stuck handler (peer hung, TCP write buffer full) must not block
    shutdown forever. ``asyncio.wait_for`` cancels the handler after
    ``per_handler_timeout``; the warning is logged and the next handler
    runs. Same shape as ``audit.flush_pending`` and
    ``ws.close_all_connections``.
    """
    monkeypatch.setattr(logging.getLogger('nori'), 'propagate', True)

    finished_after_stuck: list[str] = []

    async def stuck() -> None:
        await asyncio.sleep(60)

    async def healthy_after() -> None:
        finished_after_stuck.append('after')

    register_shutdown('stuck', stuck)
    register_shutdown('after_stuck', healthy_after)

    with caplog.at_level(logging.WARNING, logger='nori.lifecycle'):
        await run_shutdown_handlers(per_handler_timeout=0.05)

    assert any('timed out' in r.message.lower() for r in caplog.records), (
        'stuck handler must produce a timeout warning, not silent loss'
    )
    assert finished_after_stuck == ['after'], (
        'stuck handler blocked the rest of shutdown — per-handler timeout is supposed to keep the queue moving'
    )
