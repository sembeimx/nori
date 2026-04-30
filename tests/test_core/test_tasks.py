"""Tests for core.tasks."""

import pytest
from core.tasks import background, run_in_background
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
        'run_in_background must promote a single existing task to '
        'BackgroundTasks rather than overwrite it'
    )
    assert len(response.background.tasks) == 2, (
        f'expected 2 tasks queued, got {len(response.background.tasks)}'
    )


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
    assert runs == ['first', 'second'], (
        f'expected ordered execution [first, second], got {runs}'
    )


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

    assert response.background is initial, (
        'existing BackgroundTasks was replaced — should be appended in place'
    )
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
