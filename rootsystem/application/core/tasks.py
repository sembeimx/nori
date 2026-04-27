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
    """Attach a background task to an existing response."""
    response.background = background(func, *args, **kwargs)
    return response
