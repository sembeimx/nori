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

from collections.abc import Callable
from typing import Any

from starlette.background import BackgroundTask, BackgroundTasks
from starlette.responses import Response

from core.logger import get_logger

_log = get_logger('tasks')

__all__ = ['background', 'background_tasks', 'run_in_background']


def background(func: Callable[..., Any], *args: Any, **kwargs: Any) -> BackgroundTask:
    """Create a BackgroundTask that logs errors instead of crashing."""

    async def _wrapper() -> None:
        try:
            result = func(*args, **kwargs)
            if hasattr(result, '__await__'):
                await result
        except Exception as exc:
            _log.error('Background task %s failed: %s', func.__name__, exc, exc_info=True)

    return BackgroundTask(_wrapper)


def background_tasks(*tasks: tuple) -> BackgroundTasks:
    """Create multiple background tasks.

    Each element is a ``(func, args_tuple, kwargs_dict)`` triple.
    """
    bg = BackgroundTasks()
    for func, a, kw in tasks:

        async def _make_wrapper(_f=func, _a=a, _k=kw) -> None:
            try:
                result = _f(*_a, **_k)
                if hasattr(result, '__await__'):
                    await result
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
