"""Tests for core.logger module."""

import json
import logging


def test_get_logger_returns_root():
    from core.logger import get_logger

    log = get_logger()
    assert log.name == 'nori'


def test_get_logger_returns_child():
    from core.logger import get_logger

    log = get_logger('auth')
    assert log.name == 'nori.auth'


def test_get_logger_child_inherits_level():
    from core.logger import get_logger

    root = get_logger()
    child = get_logger('test_inherit')
    assert child.getEffectiveLevel() == root.level


def test_root_logger_has_handlers():
    from core.logger import get_logger

    log = get_logger()
    assert len(log.handlers) >= 1


def test_root_logger_no_propagate():
    from core.logger import get_logger

    log = get_logger()
    assert log.propagate is False


def test_json_formatter_output():
    from core.logger import _JsonFormatter

    formatter = _JsonFormatter()
    record = logging.LogRecord(
        name='test',
        level=logging.INFO,
        pathname='test.py',
        lineno=1,
        msg='hello %s',
        args=('world',),
        exc_info=None,
    )
    output = formatter.format(record)
    data = json.loads(output)
    assert data['level'] == 'INFO'
    assert data['message'] == 'hello world'
    assert data['logger'] == 'test'
    assert 'timestamp' in data


def test_json_formatter_with_exception():
    from core.logger import _JsonFormatter

    formatter = _JsonFormatter()
    try:
        raise ValueError('boom')
    except ValueError:
        import sys

        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name='test',
        level=logging.ERROR,
        pathname='test.py',
        lineno=1,
        msg='failed',
        args=(),
        exc_info=exc_info,
    )
    output = formatter.format(record)
    data = json.loads(output)
    assert 'exception' in data
    assert 'ValueError' in data['exception']


def test_text_formatter_output():
    from core.logger import _TextFormatter

    formatter = _TextFormatter()
    record = logging.LogRecord(
        name='mymodule',
        level=logging.WARNING,
        pathname='test.py',
        lineno=1,
        msg='something wrong',
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    assert 'WARNING' in output
    assert 'mymodule' in output
    assert 'something wrong' in output


def test_multiple_get_logger_calls_return_same_root():
    from core.logger import get_logger

    a = get_logger()
    b = get_logger()
    assert a is b
