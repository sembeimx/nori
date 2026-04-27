"""Tests for core.tasks."""
import pytest
from core.tasks import background, run_in_background
from starlette.background import BackgroundTask
from starlette.responses import JSONResponse


def test_background_returns_background_task():
    def noop():
        pass
    task = background(noop)
    assert isinstance(task, BackgroundTask)


def test_run_in_background_attaches_task():
    response = JSONResponse({'ok': True})
    def noop():
        pass
    result = run_in_background(response, noop)
    assert result.background is not None
    assert result is response


@pytest.mark.asyncio
async def test_background_executes_async_callable():
    results = []

    async def work(val):
        results.append(val)

    task = background(work, 42)
    await task()
    assert results == [42]


@pytest.mark.asyncio
async def test_background_executes_sync_callable():
    results = []

    def work(val):
        results.append(val)

    task = background(work, 'hello')
    await task()
    assert results == ['hello']


@pytest.mark.asyncio
async def test_background_catches_exceptions():
    def bad_task():
        raise ValueError("boom")

    task = background(bad_task)
    await task()  # should not raise
