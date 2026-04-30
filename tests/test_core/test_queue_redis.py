"""Tests for the Redis queue driver (core.queue + core.queue_worker)."""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, patch

import pytest
from core.queue import _redis_handler, push
from core.queue_worker import _work_redis

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_redis():
    """Create a mock Redis client with async methods."""
    r = AsyncMock()
    r.lpush = AsyncMock()
    r.zadd = AsyncMock()
    r.brpop = AsyncMock(return_value=None)
    r.zrangebyscore = AsyncMock(return_value=[])
    r.zrem = AsyncMock()
    r.eval = AsyncMock(return_value=0)
    return r


@pytest.fixture(autouse=True)
def _reset_redis_client():
    """Reset the global _redis_client between tests."""
    import core.queue as q

    original = q._redis_client
    q._redis_client = None
    yield
    q._redis_client = original


# ---------------------------------------------------------------------------
# _redis_handler tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redis_handler_immediate_push(mock_redis):
    """Immediate jobs are pushed to a Redis list via LPUSH."""
    with patch('core.queue._get_redis', return_value=mock_redis):
        payload = {'func': 'mod:task', 'args': ['a'], 'kwargs': {}}
        await _redis_handler('default', payload, delay=0)

    mock_redis.lpush.assert_called_once()
    call_args = mock_redis.lpush.call_args
    assert call_args[0][0] == 'nori:queue:default'
    job_data = json.loads(call_args[0][1])
    assert job_data['func'] == 'mod:task'
    assert job_data['args'] == ['a']
    assert job_data['attempts'] == 0
    assert 'queued_at' in job_data


@pytest.mark.asyncio
async def test_redis_handler_delayed_push(mock_redis):
    """Delayed jobs go to a sorted set via ZADD."""
    with patch('core.queue._get_redis', return_value=mock_redis):
        payload = {'func': 'mod:task', 'args': [], 'kwargs': {}}
        await _redis_handler('emails', payload, delay=60)

    mock_redis.zadd.assert_called_once()
    call_args = mock_redis.zadd.call_args
    assert call_args[0][0] == 'nori:queue:emails:delayed'
    score_dict = call_args[0][1]
    job_json = list(score_dict.keys())[0]
    score = list(score_dict.values())[0]
    job_data = json.loads(job_json)
    assert job_data['func'] == 'mod:task'
    assert score > time.time()  # In the future
    mock_redis.lpush.assert_not_called()


@pytest.mark.asyncio
async def test_redis_handler_custom_queue_name(mock_redis):
    """Queue name is reflected in the Redis key."""
    with patch('core.queue._get_redis', return_value=mock_redis):
        await _redis_handler('high_priority', {'func': 'x:y', 'args': [], 'kwargs': {}})

    key = mock_redis.lpush.call_args[0][0]
    assert key == 'nori:queue:high_priority'


@pytest.mark.asyncio
async def test_push_dispatches_to_redis(mock_redis, monkeypatch):
    """push() routes to the Redis handler when QUEUE_DRIVER=redis."""
    import settings

    monkeypatch.setattr(settings, 'QUEUE_DRIVER', 'redis')
    with patch('core.queue._get_redis', return_value=mock_redis):
        await push('mod:func', 'arg1', queue='test')

    mock_redis.lpush.assert_called_once()


# ---------------------------------------------------------------------------
# _work_redis tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redis_worker_processes_job(mock_redis):
    """Worker picks up a job via BRPOP and executes it."""
    job_data = json.dumps(
        {
            'func': 'tests.test_core.test_queue_redis:_dummy_task',
            'args': [],
            'kwargs': {},
            'attempts': 0,
        }
    )
    mock_redis.brpop = AsyncMock(return_value=(b'nori:queue:default', job_data.encode()))

    import core.queue_worker as qw

    qw._should_exit = False

    async def _execute_and_stop(payload):
        qw._should_exit = True

    try:
        with patch('core.queue._get_redis', return_value=mock_redis):
            with patch('core.queue_worker._register_signals'):
                with patch(
                    'core.queue_worker.execute_payload',
                    side_effect=_execute_and_stop,
                ) as mock_execute:
                    await _work_redis('default')
    finally:
        qw._should_exit = False

    mock_execute.assert_called_once()
    called_payload = mock_execute.call_args.args[0]
    assert called_payload['func'] == 'tests.test_core.test_queue_redis:_dummy_task'
    assert called_payload['attempts'] == 0


@pytest.mark.asyncio
async def test_redis_worker_retries_failed_job(mock_redis):
    """Failed jobs are re-queued to the delayed sorted set with backoff."""
    job_data = json.dumps(
        {
            'func': 'tests.test_core.test_queue_redis:_failing_task',
            'args': [],
            'kwargs': {},
            'attempts': 0,
        }
    )

    mock_redis.brpop = AsyncMock(return_value=(b'nori:queue:retry', job_data.encode()))

    import core.queue_worker as qw

    qw._should_exit = False

    with patch('core.queue._get_redis', return_value=mock_redis):
        with patch('core.queue_worker._register_signals'):

            async def _fail_and_stop(payload):
                qw._should_exit = True
                raise Exception('Intentional failure')

            with patch('core.queue_worker.execute_payload', side_effect=_fail_and_stop):
                await _work_redis('retry')

    # Should have re-queued to delayed set
    mock_redis.zadd.assert_called_once()
    call_args = mock_redis.zadd.call_args[0]
    assert call_args[0] == 'nori:queue:retry:delayed'
    retried_job = json.loads(list(call_args[1].keys())[0])
    assert retried_job['attempts'] == 1

    qw._should_exit = False


@pytest.mark.asyncio
async def test_redis_worker_dead_letters_after_max_attempts(mock_redis):
    """After MAX_ATTEMPTS, failed jobs go to the :failed list."""
    from core.queue_worker import MAX_ATTEMPTS

    job_data = json.dumps(
        {
            'func': 'tests.test_core.test_queue_redis:_failing_task',
            'args': [],
            'kwargs': {},
            'attempts': MAX_ATTEMPTS - 1,
        }
    )

    mock_redis.brpop = AsyncMock(return_value=(b'nori:queue:dead', job_data.encode()))

    import core.queue_worker as qw

    qw._should_exit = False

    with patch('core.queue._get_redis', return_value=mock_redis):
        with patch('core.queue_worker._register_signals'):

            async def _fail_and_stop(payload):
                qw._should_exit = True
                raise Exception('Final failure')

            with patch('core.queue_worker.execute_payload', side_effect=_fail_and_stop):
                await _work_redis('dead')

    # Should go to :failed list, NOT :delayed
    mock_redis.lpush.assert_called_once()
    failed_key = mock_redis.lpush.call_args[0][0]
    assert failed_key == 'nori:queue:dead:failed'
    failed_job = json.loads(mock_redis.lpush.call_args[0][1])
    assert failed_job['attempts'] == MAX_ATTEMPTS
    assert 'failed_at' in failed_job
    mock_redis.zadd.assert_not_called()

    qw._should_exit = False


@pytest.mark.asyncio
async def test_redis_worker_promotes_delayed_jobs_atomically(mock_redis):
    """Delayed jobs are promoted via a single Lua EVAL — not the non-atomic
    ZRANGEBYSCORE + LPUSH + ZREM sequence that races across workers and
    double-executes the same job under multi-worker deployments."""
    mock_redis.brpop = AsyncMock(return_value=None)

    import core.queue_worker as qw

    qw._should_exit = False

    call_count = 0

    async def _eval_then_stop(*a, **kw):
        nonlocal call_count
        call_count += 1
        if call_count >= 1:
            qw._should_exit = True
        return 1  # number of items promoted

    mock_redis.eval = AsyncMock(side_effect=_eval_then_stop)

    with patch('core.queue._get_redis', return_value=mock_redis):
        with patch('core.queue_worker._register_signals'):
            await _work_redis('promo')

    # Verify EVAL was called with the right keys, args, and Lua body
    mock_redis.eval.assert_called()
    eval_args = mock_redis.eval.call_args[0]
    script, numkeys, delayed_key, main_key, score = eval_args[:5]

    assert 'ZRANGEBYSCORE' in script
    assert 'LPUSH' in script
    assert 'ZREM' in script
    assert numkeys == 2
    assert delayed_key == 'nori:queue:promo:delayed'
    assert main_key == 'nori:queue:promo'
    assert isinstance(score, (int, float))

    # The non-atomic primitives must NOT be invoked directly during promotion
    mock_redis.zrangebyscore.assert_not_called()
    mock_redis.zrem.assert_not_called()
    # lpush is reserved for dead-letter writes; not used here because brpop returns None

    qw._should_exit = False


# ---------------------------------------------------------------------------
# Dummy tasks for testing
# ---------------------------------------------------------------------------


async def _dummy_task():
    pass


async def _failing_task():
    raise Exception('I always fail')
