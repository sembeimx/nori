"""Tests for the persistent queue system (core.queue and core.queue_worker)."""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add project root to sys.path so 'tests' module is importable by the worker
_root = str(Path(__file__).parents[2])
if _root not in sys.path:
    sys.path.insert(0, _root)

from datetime import timedelta

from core.queue import push
from core.queue_worker import MAX_ATTEMPTS, work
from models.framework.job import Job
from tortoise.timezone import now


@pytest.fixture(autouse=True)
async def _clean_db():
    await Job.all().delete()
    yield
    await Job.all().delete()


@pytest.fixture(autouse=True)
def _force_db_driver(monkeypatch):
    import settings

    monkeypatch.setattr(settings, 'QUEUE_DRIVER', 'database')
    monkeypatch.setattr(settings, 'DB_ENABLED', True)
    # The dummy tasks below live under tests.*, which is outside the default
    # production allow-list. Tests opt into the prefix explicitly.
    monkeypatch.setattr(
        settings,
        'QUEUE_ALLOWED_MODULES',
        ['tests.', 'modules.', 'services.', 'app.', 'tasks.'],
    )


# -- Dummy tasks for testing -------------------------------------------------

TRACKER_FILE = os.path.join(tempfile.gettempdir(), 'nori_queue_test.txt')


def _mark_executed(msg: str):
    with open(TRACKER_FILE, 'a') as f:
        f.write(msg + '\n')


def _get_executed() -> list[str]:
    if not os.path.exists(TRACKER_FILE):
        return []
    with open(TRACKER_FILE) as f:
        return [line.strip() for f in [f] for line in f if line.strip()]


@pytest.fixture(autouse=True)
def _clear_tracker():
    if os.path.exists(TRACKER_FILE):
        os.remove(TRACKER_FILE)
    yield
    if os.path.exists(TRACKER_FILE):
        os.remove(TRACKER_FILE)


async def success_task(name: str):
    _mark_executed(f'success:{name}')


async def fail_task(name: str):
    _mark_executed(f'fail:{name}')
    raise Exception('Task failed intentionally')


# v1.30 regression helpers — defined at module level so
# ``importlib.import_module(...)`` (potentially loading the module a
# second time under a different name from pytest's collection) finds
# them in the fresh module's namespace, not just on whichever instance
# pytest happens to have populated.


async def gc_marker_task(name: str) -> None:
    """Used by ``test_memory_handler_holds_strong_reference_to_task``.
    The body is what we assert ran; if the in-flight Task is GC-collected
    pre-fix, this never executes and the file tracker stays empty.
    """
    _mark_executed(f'gc-marker:{name}')


def blocking_sync_handler() -> None:
    """Sync sleep used by ``test_execute_payload_offloads_sync_callable_to_thread``.
    Pre-fix this body would block the event loop because ``execute_payload``
    called sync callables inline.
    """
    import time as _time

    _time.sleep(0.2)


def sync_factory_returning_coroutine(arg: str) -> object:
    """Legacy / hybrid pattern: sync function returning an awaitable.
    Sync portion must run in a thread, the returned coroutine on the loop.
    """
    _mark_executed(f'sync:{arg}')

    async def _inner() -> None:
        _mark_executed(f'async:{arg}')

    return _inner()


async def async_loop_probe() -> None:
    """Records that the handler ran with a running event loop —
    ``asyncio.get_running_loop()`` raises ``RuntimeError`` if not on one.
    """
    asyncio.get_running_loop()
    _mark_executed('on-loop')


# -- Tests -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_push_adds_job_to_db():
    await push('tests.test_core.test_queue:success_task', 'hello', queue='test_queue')
    job = await Job.filter(queue='test_queue').first()
    assert job is not None
    assert job.payload['func'] == 'tests.test_core.test_queue:success_task'
    assert job.payload['args'] == ['hello']


@pytest.mark.asyncio
async def test_worker_processes_successful_job():
    await push('tests.test_core.test_queue:success_task', 'worker_test', queue='worker_queue')

    # Run worker briefly
    worker_task = asyncio.create_task(work(queue_name='worker_queue', sleep=0.1))
    await asyncio.sleep(0.8)  # Wait a bit longer
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

    assert 'success:worker_test' in _get_executed()
    # Job should be deleted from DB after success
    count = await Job.filter(queue='worker_queue').count()
    assert count == 0


@pytest.mark.asyncio
async def test_worker_retries_failed_job_with_backoff():
    await push('tests.test_core.test_queue:fail_task', 'retry_test', queue='retry_queue')

    # Run worker briefly
    worker_task = asyncio.create_task(work(queue_name='retry_queue', sleep=0.1))
    await asyncio.sleep(0.8)
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

    assert 'fail:retry_test' in _get_executed()

    job = await Job.filter(queue='retry_queue').first()
    assert job is not None
    assert job.attempts >= 1
    assert job.reserved_at is None
    # available_at should be in the future (backoff)
    assert job.available_at > now()


@pytest.mark.asyncio
async def test_worker_marks_job_as_failed_after_max_attempts():
    # Create a job that is on its last attempt
    payload = {'func': 'tests.test_core.test_queue:fail_task', 'args': ['dead_letter'], 'kwargs': {}}
    await Job.create(
        queue='dead_queue',
        payload=payload,
        attempts=MAX_ATTEMPTS - 1,
        available_at=now() - timedelta(seconds=1),  # Ensure it's ready
    )

    # Run worker briefly
    worker_task = asyncio.create_task(work(queue_name='dead_queue', sleep=0.1))
    await asyncio.sleep(0.8)
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

    job = await Job.filter(queue='dead_queue').first()
    assert job is not None
    assert job.attempts == MAX_ATTEMPTS
    assert job.failed_at is not None
    assert job.reserved_at is None


@pytest.mark.asyncio
async def test_atomic_reservation():
    """Verify that multiple workers don't grab the same job."""
    await push('tests.test_core.test_queue:success_task', 'atomic', queue='atomic_queue')

    # Start two workers
    w1 = asyncio.create_task(work(queue_name='atomic_queue', sleep=0.1))
    w2 = asyncio.create_task(work(queue_name='atomic_queue', sleep=0.1))

    await asyncio.sleep(1.0)
    w1.cancel()
    w2.cancel()

    # success_task should only have been executed ONCE
    executed = _get_executed()
    assert len(executed) == 1
    assert executed[0] == 'success:atomic'


# -- Module allow-list (RCE defense) -----------------------------------------


@pytest.mark.asyncio
async def test_execute_payload_blocks_os_system(monkeypatch):
    """A payload pointing at `os:system` (the canonical RCE vector) is rejected
    before importlib.import_module runs."""
    import settings

    monkeypatch.setattr(settings, 'QUEUE_ALLOWED_MODULES', ['modules.', 'services.', 'app.', 'tasks.'])
    from core.queue_worker import execute_payload

    payload = {'func': 'os:system', 'args': ['echo pwned'], 'kwargs': {}}
    with pytest.raises(PermissionError, match='not in QUEUE_ALLOWED_MODULES'):
        await execute_payload(payload)


@pytest.mark.asyncio
async def test_execute_payload_blocks_subprocess(monkeypatch):
    import settings

    monkeypatch.setattr(settings, 'QUEUE_ALLOWED_MODULES', ['modules.'])
    from core.queue_worker import execute_payload

    payload = {'func': 'subprocess:run', 'args': [['ls']], 'kwargs': {}}
    with pytest.raises(PermissionError):
        await execute_payload(payload)


@pytest.mark.asyncio
async def test_execute_payload_blocks_builtins_exec(monkeypatch):
    """builtins.exec is the most direct code-injection primitive — must be
    blocked even though `builtins` is always importable."""
    import settings

    monkeypatch.setattr(settings, 'QUEUE_ALLOWED_MODULES', ['modules.'])
    from core.queue_worker import execute_payload

    payload = {'func': 'builtins:exec', 'args': ['print(1)'], 'kwargs': {}}
    with pytest.raises(PermissionError):
        await execute_payload(payload)


@pytest.mark.asyncio
async def test_execute_payload_blocks_prefix_attack(monkeypatch):
    """Prefix without trailing dot must not match strings sharing only the prefix.

    A user setting QUEUE_ALLOWED_MODULES=['modules'] (no dot) is normalized
    internally to 'modules.', so 'modules_evil:exploit' stays blocked —
    'modules_evil.' does not start with 'modules.'.
    """
    import settings

    monkeypatch.setattr(settings, 'QUEUE_ALLOWED_MODULES', ['modules'])
    from core.queue_worker import execute_payload

    payload = {'func': 'modules_evil:exploit', 'args': [], 'kwargs': {}}
    with pytest.raises(PermissionError):
        await execute_payload(payload)


@pytest.mark.asyncio
async def test_execute_payload_respects_custom_allow_list(monkeypatch):
    """Custom QUEUE_ALLOWED_MODULES overrides the defaults entirely."""
    import settings

    monkeypatch.setattr(settings, 'QUEUE_ALLOWED_MODULES', ['my_jobs.'])
    from core.queue_worker import execute_payload

    # `modules.` is no longer allowed because the user narrowed the list.
    payload = {'func': 'modules.foo:bar', 'args': [], 'kwargs': {}}
    with pytest.raises(PermissionError):
        await execute_payload(payload)


@pytest.mark.asyncio
async def test_execute_payload_allows_listed_module():
    """Sanity check: an allowed module path runs through to importlib."""
    from core.queue_worker import execute_payload

    payload = {'func': 'tests.test_core.test_queue:success_task', 'args': ['allowed'], 'kwargs': {}}
    await execute_payload(payload)
    assert 'success:allowed' in _get_executed()


@pytest.mark.asyncio
async def test_execute_payload_rejects_dotted_func_name(monkeypatch):
    """A func name with dots must be refused before getattr.

    ``getattr`` does not recurse on dots so 'os.system' would land as
    a literal attribute name and AttributeError, but rejecting up front
    makes the contract obvious — and avoids relying on a quirk.
    """
    from core.queue_worker import execute_payload

    payload = {'func': 'tasks:os.system', 'args': [], 'kwargs': {}}
    with pytest.raises(ValueError, match='Invalid queue function name'):
        await execute_payload(payload)


@pytest.mark.asyncio
async def test_execute_payload_rejects_re_exported_os_system(monkeypatch, tmp_path):
    """Defence in depth: even if an allow-listed module re-exports
    os.system via ``from os import system``, calling it through the
    queue must still be refused.

    Pre-1.23.0 the worker only validated ``mod_path``. After getattr
    pulled the alias, it called the function — meaning a single
    ``from os import system`` in any allow-listed module became an RCE
    primitive for whoever could write to the queue store.
    """
    import sys

    # Build a fake allow-listed package that re-exports os.system.
    pkg_dir = tmp_path / 'fakepkg'
    pkg_dir.mkdir()
    (pkg_dir / '__init__.py').write_text('')
    (pkg_dir / 'jobs.py').write_text('from os import system\n')
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop('fakepkg', None)
    sys.modules.pop('fakepkg.jobs', None)

    import settings

    monkeypatch.setattr(settings, 'QUEUE_ALLOWED_MODULES', ['fakepkg.'])
    from core.queue_worker import execute_payload

    payload = {'func': 'fakepkg.jobs:system', 'args': ['echo pwned'], 'kwargs': {}}
    with pytest.raises(PermissionError, match=r'__module__'):
        await execute_payload(payload)


@pytest.mark.asyncio
async def test_execute_payload_rejects_non_callable_attribute(monkeypatch):
    """A getattr that resolves to a non-callable (a constant, a dict, a
    submodule) must raise rather than fail later in the call site."""
    import sys

    import settings

    monkeypatch.setattr(settings, 'QUEUE_ALLOWED_MODULES', ['tests.'])
    from core.queue_worker import execute_payload

    # Add a non-callable attribute to this test module.
    sys.modules[__name__].some_constant = 42  # type: ignore[attr-defined]

    payload = {'func': 'tests.test_core.test_queue:some_constant', 'args': [], 'kwargs': {}}
    with pytest.raises(ValueError, match='not callable'):
        await execute_payload(payload)


# -- Job table bloat regression ----------------------------------------------


def test_job_model_does_not_use_soft_deletes():
    """The Job model MUST NOT inherit NoriSoftDeletes.

    The worker hard-deletes successful jobs to prevent the table from
    growing unboundedly. If someone wires NoriSoftDeletes into Job
    (intentionally or by reflex), `await job.delete()` becomes
    `UPDATE deleted_at=NOW()` and processed rows pile up forever —
    polling queries get slower with every job ever run.
    """
    from core.mixins.soft_deletes import NoriSoftDeletes
    from models.framework.job import Job

    assert not issubclass(Job, NoriSoftDeletes), (
        'Job inherits NoriSoftDeletes — the queue worker uses hard delete '
        'to drop completed jobs. With soft delete the jobs table grows '
        'indefinitely. See models/framework/job.py for the rationale.'
    )


# -- Memory driver: strong reference to in-flight tasks ---------------------


@pytest.mark.asyncio
async def test_memory_handler_holds_strong_reference_to_task():
    """Pre-1.30 ``_memory_handler`` did ``asyncio.create_task(_run())`` and
    threw the returned Task away — Python's event loop holds only a weak
    reference to a Task, so an unreferenced task can be garbage-collected
    mid-``await asyncio.sleep(delay)``. The user-visible failure: a
    ``push('mail.send', delay=30)`` would silently never run.
    The fix mirrors ``core.audit._pending_tasks``: a module-level set
    pins the task until ``add_done_callback(set.discard)`` releases it.
    """
    from core.queue import _memory_handler, _memory_tasks

    initial = len(_memory_tasks)

    payload = {
        'func': 'tests.test_core.test_queue:gc_marker_task',
        'args': ['gc-test'],
        'kwargs': {},
    }
    await _memory_handler('q', payload, delay=0)

    # Right after the handler returns, the Task has been created but
    # has NOT had a chance to run its body yet (control returns from
    # ``asyncio.create_task`` synchronously). The set must hold a
    # strong reference; without one the loop's weak ref is the only
    # reference and an aggressive GC pass could collect the Task.
    assert len(_memory_tasks) == initial + 1, (
        f'task not pinned in _memory_tasks (size went {initial} → '
        f'{len(_memory_tasks)}); pre-fix the Task was subject to GC '
        f'mid-sleep and the job would silently never run'
    )

    # Yield long enough for the task to run end-to-end.
    await asyncio.sleep(0.1)

    assert 'gc-marker:gc-test' in _get_executed(), (
        'handler body did not execute — the Task was apparently lost between scheduling and resumption'
    )
    assert len(_memory_tasks) == initial, (
        'done callback did not release the task from _memory_tasks; the '
        'set would grow unboundedly across in-flight jobs'
    )


# -- queue_worker: sync callable offload to thread ---------------------------


@pytest.mark.asyncio
async def test_execute_payload_offloads_sync_callable_to_thread():
    """A synchronous callable dispatched through ``execute_payload`` MUST
    run in a worker thread — running it inline on the loop freezes every
    other request for the duration of the call. Under the memory queue
    driver this is especially severe (the dispatch happens inside the
    ASGI event loop, not a worker process).
    Same shape as the v1.27.0 ``core.tasks._run()`` fix for
    ``background()``: sync callables go through ``asyncio.to_thread``.
    The test runs a 200 ms blocking ``time.sleep`` and concurrently
    advances a 10 ms ticker on the loop. If the sync portion ran inline
    the ticker would advance ~zero times during the block; with the
    offload it must advance several.
    """
    from core.queue_worker import execute_payload

    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    ticker_task = asyncio.create_task(ticker())
    try:
        payload = {
            'func': 'tests.test_core.test_queue:blocking_sync_handler',
            'args': [],
            'kwargs': {},
        }
        await execute_payload(payload)
    finally:
        ticker_task.cancel()
        try:
            await ticker_task
        except asyncio.CancelledError:
            pass

    assert ticks >= 5, (
        f'ticker advanced only {ticks} times during a 200 ms sync call — '
        f'execute_payload blocked the loop instead of offloading via '
        f'asyncio.to_thread'
    )


@pytest.mark.asyncio
async def test_execute_payload_runs_sync_factory_returning_coroutine():
    """Legacy / hybrid pattern: a sync function whose return value is an
    awaitable. The fix keeps this working — the sync portion runs in a
    worker thread, the resulting awaitable is awaited on the loop.
    """
    from core.queue_worker import execute_payload

    payload = {
        'func': 'tests.test_core.test_queue:sync_factory_returning_coroutine',
        'args': ['x'],
        'kwargs': {},
    }
    await execute_payload(payload)
    assert 'sync:x' in _get_executed()
    assert 'async:x' in _get_executed()


@pytest.mark.asyncio
async def test_execute_payload_async_callable_still_runs_on_loop():
    """An async ``def`` target must continue to be ``await``-ed directly
    on the loop, not handed to ``asyncio.to_thread`` (which would either
    schedule the coroutine on a thread that has no loop, or — worse —
    return the unawaited coroutine and let it leak).
    """
    from core.queue_worker import execute_payload

    payload = {
        'func': 'tests.test_core.test_queue:async_loop_probe',
        'args': [],
        'kwargs': {},
    }
    await execute_payload(payload)
    assert 'on-loop' in _get_executed()
