"""
Nori bootstrap hook.

Loads an optional `bootstrap.py` from the application root so a site can
run code BEFORE the framework imports Starlette, Tortoise, or anything
instrumentable. This is the correct moment to initialise observability
SDKs (Sentry, Datadog, OpenTelemetry) that patch libraries at import time.

Usage — create `rootsystem/application/bootstrap.py`:

    def bootstrap() -> None:
        import os, sentry_sdk
        if dsn := os.environ.get('SENTRY_DSN'):
            sentry_sdk.init(dsn=dsn, traces_sample_rate=0.1)

The file is optional. If absent, `load_bootstrap()` is a no-op. If the
file imports or `bootstrap()` raises, a warning is logged and the app
continues to start — never crash the server because of a user hook.
"""
from __future__ import annotations

import importlib
import importlib.util
import logging

_bootstrapped = False
_log = logging.getLogger('nori.bootstrap')


def load_bootstrap() -> None:
    global _bootstrapped
    if _bootstrapped:
        return
    _bootstrapped = True

    if importlib.util.find_spec('bootstrap') is None:
        return

    try:
        module = importlib.import_module('bootstrap')
    except Exception as e:
        _log.warning('bootstrap.py failed to import: %s', e, exc_info=True)
        return

    hook = getattr(module, 'bootstrap', None)
    if not callable(hook):
        return

    try:
        hook()
    except Exception as e:
        _log.warning('bootstrap() raised: %s', e, exc_info=True)


def _reset_for_tests() -> None:
    global _bootstrapped
    _bootstrapped = False
