"""
Background task utilities wrapping Starlette's BackgroundTask.

Usage::

    from core.tasks import background, run_in_background

    # Option 1: create task, pass to response
    task = background(send_email, to='user@example.com')
    return JSONResponse({'ok': True}, background=task)

    # Option 2: attach to existing response
    response = JSONResponse({'ok': True})
    return run_in_background(response, send_email, to='user@example.com')
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from typing import Any

from starlette.background import BackgroundTask, BackgroundTasks
from starlette.responses import Response

from core.logger import get_logger

_log = get_logger('tasks')

__all__ = ['background', 'background_tasks', 'run_in_background']


async def _run(func: Callable[..., Any], args: tuple, kwargs: dict) -> None:
    """Run ``func`` cooperatively — async funcs are awaited, sync funcs run in a worker thread.

    Pre-1.27 the wrapper was unconditionally ``async def`` and called the
    user's callable directly inside it; if the callable was synchronous
    (e.g. a legacy mail SDK, an image-processing routine, ``time.sleep``,
    ``requests.get``), Starlette could not detect the sync nature
    (because Starlette's ``BackgroundTask`` saw an async wrapper and
    skipped its own ``run_in_threadpool`` path) and the function ran on
    the event loop, blocking every other request for the duration. The
    "background-safe" promise of this helper failed silently for any
    sync callable.

    The current implementation matches Starlette's own dispatch:
    coroutine functions are awaited directly; everything else is
    offloaded to a worker thread via ``asyncio.to_thread``. A sync
    callable that returns an awaitable (the legacy "factory" pattern)
    still works — the sync portion runs in the thread, the awaitable is
    awaited on the loop. Errors from either path are logged at ERROR
    via the caller's wrapper; this helper itself is intentionally
    minimal.
    """
    if inspect.iscoroutinefunction(func):
        await func(*args, **kwargs)
        return
    # Sync callable — run in the default thread executor so blocking I/O
    # or CPU-bound work does not freeze the event loop.
    result = await asyncio.to_thread(func, *args, **kwargs)
    if inspect.isawaitable(result):
        # Factory pattern: a sync function whose return value is a
        # coroutine. The factory ran in the thread; the coroutine itself
        # must be awaited on the loop where it was created.
        await result


def background(func: Callable[..., Any], *args: Any, **kwargs: Any) -> BackgroundTask:
    """Create a BackgroundTask that logs errors instead of crashing.

    The returned task offloads synchronous callables to a worker thread
    via ``asyncio.to_thread`` so a slow sync function does not block the
    event loop. Coroutine functions are awaited directly. See ``_run``
    for the dispatch detail.
    """

    async def _wrapper() -> None:
        try:
            await _run(func, args, kwargs)
        except Exception as exc:
            _log.error('Background task %s failed: %s', func.__name__, exc, exc_info=True)

    return BackgroundTask(_wrapper)


def background_tasks(*tasks: tuple) -> BackgroundTasks:
    """Create multiple background tasks.

    Each element is a ``(func, args_tuple, kwargs_dict)`` triple. Each
    task uses the same sync/async dispatch as :func:`background` — sync
    callables run in a worker thread, coroutine functions on the loop.
    """
    bg = BackgroundTasks()
    for func, a, kw in tasks:

        async def _make_wrapper(_f=func, _a=a, _k=kw) -> None:
            try:
                await _run(_f, _a, _k)
            except Exception as exc:
                _log.error('Background task %s failed: %s', _f.__name__, exc, exc_info=True)

        bg.add_task(_make_wrapper)
    return bg


def run_in_background(
    response: Response,
    func: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> Response:
    """Attach a background task to an existing response, accumulating safely.

    Pre-1.25 this assigned ``response.background = background(...)``
    unconditionally, silently overwriting any task already attached. A
    controller that returned ``JSONResponse({...},
    background=send_email_task)`` and then went through a decorator /
    middleware that called ``run_in_background(response, audit_log)``
    lost the email task — the response shipped only the audit task,
    and the user never got their email. The bug is invisible until the
    first time you compose tasks across layers.

    The fix promotes to Starlette's ``BackgroundTasks`` (plural) the
    moment a second task arrives:

    * No existing task → set the new one directly (no wrapper allocation).
    * Existing ``BackgroundTasks`` → append to it.
    * Existing single ``BackgroundTask`` → wrap both into a fresh
      ``BackgroundTasks`` and replace.

    Tasks run in the order they were attached, matching how Starlette
    iterates ``BackgroundTasks.tasks``.
    """
    new_task = background(func, *args, **kwargs)
    existing = response.background

    if existing is None:
        response.background = new_task
    elif isinstance(existing, BackgroundTasks):
        existing.tasks.append(new_task)
    else:
        merged = BackgroundTasks()
        merged.tasks.append(existing)
        merged.tasks.append(new_task)
        response.background = merged

    return response
