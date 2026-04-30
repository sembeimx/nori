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

    monkeypatch.setattr(
        settings, 'QUEUE_ALLOWED_MODULES', ['modules.', 'services.', 'app.', 'tasks.']
    )
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
