"""Shutdown handler registry — close service-driver resources at lifespan teardown.

Service drivers under ``services/*`` typically hold a module-level
``httpx.AsyncClient`` for connection pooling (S3, GCS, OAuth providers,
mail, search). Each one already exposes a ``shutdown()`` coroutine that
``await``-s ``client.aclose()``. Pre-1.27 nobody called those — the ASGI
lifespan tore down DB connections and exited, and every active TCP/TLS
connection in those pools was left to the OS to reap. In dev that
manifested as steady file-descriptor accumulation across hot-reloads;
in production it manifested as half-open sockets piling up across
rolling restarts and graceful redeploys.

This module is the missing wiring. Service drivers register their
``shutdown`` here on first resource use; the ASGI lifespan iterates the
registry and awaits each entry before tearing down DB connections. A
stuck handler does not block the rest of shutdown — each one runs with
its own short timeout and errors are logged but never re-raised.

Service-side registration pattern::

    def _get_client() -> httpx.AsyncClient:
        global _client
        if _client is None:
            _client = httpx.AsyncClient(timeout=30.0)
            from core.lifecycle import register_shutdown
            register_shutdown('oauth_github', shutdown)
        return _client

Registering on first use (rather than at module import) keeps the
registry empty for services the project never actually exercises — a
project that only uses Meilisearch should not be paying the shutdown
cost of S3 / GCS / OAuth clients it never instantiated.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from core.logger import get_logger

_log = get_logger('lifecycle')

__all__ = [
    'register_shutdown',
    'run_shutdown_handlers',
]

_shutdown_handlers: list[tuple[str, Callable[[], Awaitable[None]]]] = []


def register_shutdown(name: str, handler: Callable[[], Awaitable[None]]) -> None:
    """Register an async ``handler`` to be invoked at ASGI lifespan teardown.

    Idempotent: registering the *same* handler object more than once is
    a no-op. This matters because ``_get_client()`` calls in service
    drivers register on first use, and a hot-reload that re-imports the
    driver would otherwise stack duplicate entries that all close the
    same (already-replaced) client.

    The ``name`` field is informational — it appears in log lines when a
    handler times out or raises, so use a short identifier matching the
    service module (``'oauth_github'``, ``'storage_s3'``, etc.).
    """
    if any(h is handler for _, h in _shutdown_handlers):
        return
    _shutdown_handlers.append((name, handler))


async def run_shutdown_handlers(per_handler_timeout: float = 5.0) -> None:
    """Invoke every registered shutdown handler, swallowing per-handler errors.

    Handlers run sequentially with their own ``per_handler_timeout`` so
    one stuck handler cannot prevent the others from running. Errors
    (and timeouts) are logged but do NOT propagate — graceful shutdown
    must keep moving even if a single driver's ``aclose`` hangs on a
    half-dead peer.

    The intentional trade is "noisy partial shutdown" over "hung
    process". Same shape as :func:`core.audit.flush_pending` and
    :func:`core.ws.close_all_connections`.
    """
    if not _shutdown_handlers:
        return
    for name, handler in _shutdown_handlers:
        try:
            await asyncio.wait_for(handler(), timeout=per_handler_timeout)
        except (TimeoutError, asyncio.TimeoutError):
            _log.warning(
                'Shutdown handler %r timed out after %.1fs; continuing.',
                name,
                per_handler_timeout,
            )
        except Exception as exc:
            _log.error(
                'Shutdown handler %r failed: %s',
                name,
                exc,
                exc_info=True,
            )


def _reset_for_tests() -> None:
    """Clear the registry. For test fixtures only — production code must
    never call this. Public state changes only via ``register_shutdown``.
    """
    _shutdown_handlers.clear()
