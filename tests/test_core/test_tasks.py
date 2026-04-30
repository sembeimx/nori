"""Tests for core.tasks."""

import pytest
from core.tasks import background, background_tasks, run_in_background
from starlette.background import BackgroundTask, BackgroundTasks
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
        raise ValueError('boom')

    task = background(bad_task)
    await task()  # should not raise


# ---------------------------------------------------------------------------
# run_in_background — composition / accumulation regression (MED)
# ---------------------------------------------------------------------------


def test_run_in_background_does_not_overwrite_existing_task():
    """A controller that already attached a task (e.g. send_email) and
    then runs through a layer that calls run_in_background (audit_log)
    must end up with BOTH tasks scheduled. Pre-1.25 the assignment was
    unconditional, so the email was silently dropped.
    """
    first_runs: list[str] = []
    second_runs: list[str] = []

    async def send_email() -> None:
        first_runs.append('email')

    async def audit_log() -> None:
        second_runs.append('audit')

    initial_task = background(send_email)
    response = JSONResponse({'ok': True}, background=initial_task)

    run_in_background(response, audit_log)

    assert isinstance(response.background, BackgroundTasks), (
        'run_in_background must promote a single existing task to BackgroundTasks rather than overwrite it'
    )
    assert len(response.background.tasks) == 2, f'expected 2 tasks queued, got {len(response.background.tasks)}'


@pytest.mark.asyncio
async def test_run_in_background_runs_both_existing_and_new_task():
    """End-to-end: invoke the merged BackgroundTasks and assert both
    callables ran. Verifies the wrapper does not just hold references —
    iteration in Starlette's order actually executes them."""
    runs: list[str] = []

    async def first() -> None:
        runs.append('first')

    async def second() -> None:
        runs.append('second')

    response = JSONResponse({'ok': True}, background=background(first))
    run_in_background(response, second)

    await response.background()
    assert runs == ['first', 'second'], f'expected ordered execution [first, second], got {runs}'


def test_run_in_background_appends_to_existing_background_tasks():
    """If the controller already used ``BackgroundTasks`` (plural),
    additional ``run_in_background`` calls must extend that container
    in place rather than wrap it again — wrapping a wrapper would
    work but would allocate a stack of nested BackgroundTasks for a
    chain of N decorators."""
    initial = BackgroundTasks()

    async def t1() -> None: ...

    async def t2() -> None: ...

    initial.tasks.append(background(t1))
    response = JSONResponse({'ok': True}, background=initial)

    run_in_background(response, t2)

    assert response.background is initial, 'existing BackgroundTasks was replaced — should be appended in place'
    assert len(initial.tasks) == 2


def test_run_in_background_attaches_directly_when_no_existing_task():
    """No regression on the single-task path: when the response has no
    existing background, the new task lands directly (no needless
    BackgroundTasks wrapper allocation)."""

    async def only() -> None: ...

    response = JSONResponse({'ok': True})
    assert response.background is None  # sanity

    run_in_background(response, only)

    assert isinstance(response.background, BackgroundTask)
    assert not isinstance(response.background, BackgroundTasks)


# ---------------------------------------------------------------------------
# background() — sync callable must NOT block the event loop (HIGH)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_background_sync_callable_does_not_block_event_loop():
    """A blocking sync function passed to ``background()`` must run in a
    worker thread, NOT on the event loop.

    Pre-1.27 ``background()`` wrapped every callable in ``async def``,
    so Starlette's own sync detection (``run_in_threadpool``) was
    bypassed and a sync callable ran inline on the loop. This test
    proves cooperative behavior by running a "blocking" sync function
    concurrently with an event-loop ticker; if the sync function were
    on the loop, the ticker would advance ~zero times during the
    block. With offloading, the ticker keeps running.
    """
    import asyncio
    import time

    sync_completed = asyncio.Event()
    ticker_count = 0

    def slow_sync() -> None:
        # 200 ms blocking sleep — short enough to keep the test fast,
        # long enough that a loop blocked here would tick ~zero times.
        time.sleep(0.2)
        sync_completed.set()

    async def ticker() -> None:
        nonlocal ticker_count
        while not sync_completed.is_set():
            ticker_count += 1
            await asyncio.sleep(0.005)

    task = background(slow_sync)

    # Run the BackgroundTask and the ticker concurrently. If background()
    # offloads the sync call (1.27+), the ticker advances many times
    # during the block. If it runs sync on the loop (pre-1.27), the
    # ticker is starved and ticker_count stays near 0.
    await asyncio.gather(task(), ticker())

    assert sync_completed.is_set(), 'sync callable did not complete'
    assert ticker_count >= 5, (
        f'event loop was blocked by sync callable — ticker advanced '
        f'only {ticker_count} times during a 200 ms sleep. '
        f'background() is running sync code on the loop instead of '
        f'asyncio.to_thread.'
    )


@pytest.mark.asyncio
async def test_background_async_callable_runs_on_event_loop():
    """No regression: coroutine functions must still be awaited directly
    on the loop, not pushed through ``asyncio.to_thread`` (which would
    fail because the coroutine cannot be awaited from a worker thread
    that has no running event loop)."""
    runs: list[str] = []

    async def async_work() -> None:
        runs.append('did-async')

    task = background(async_work)
    await task()

    assert runs == ['did-async']


@pytest.mark.asyncio
async def test_background_handles_sync_factory_returning_coroutine():
    """Legacy/edge pattern: a sync function that *returns* a coroutine
    object. The sync factory call must run in the worker thread, but
    the resulting coroutine must be awaited on the loop (you cannot
    await a coroutine from inside a thread without a running loop).
    """
    runs: list[str] = []

    async def real_work() -> None:
        runs.append('awaited')

    def sync_factory():
        return real_work()

    task = background(sync_factory)
    await task()

    assert runs == ['awaited']


@pytest.mark.asyncio
async def test_background_tasks_plural_offloads_sync_callables():
    """The plural variant must use the same sync/async dispatch — pre-1.27
    it had its own copy of the bug (``hasattr(result, '__await__')``
    after a sync call on the loop)."""
    import asyncio
    import time

    completed = asyncio.Event()
    ticker_count = 0

    def slow_sync() -> None:
        time.sleep(0.2)
        completed.set()

    async def ticker() -> None:
        nonlocal ticker_count
        while not completed.is_set():
            ticker_count += 1
            await asyncio.sleep(0.005)

    bg = background_tasks((slow_sync, (), {}))
    await asyncio.gather(bg(), ticker())

    assert completed.is_set()
    assert ticker_count >= 5, f'background_tasks() blocked the loop on a sync callable (ticker_count={ticker_count})'
