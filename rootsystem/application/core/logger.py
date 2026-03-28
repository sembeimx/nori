from __future__ import annotations

"""
Nori Logger -- production-grade logging with rotation and optional JSON output.

Configuration via environment variables:
    LOG_LEVEL   = DEBUG | INFO | WARNING | ERROR | CRITICAL  (default: DEBUG if DEBUG else INFO)
    LOG_FORMAT  = text | json                                (default: text)
    LOG_FILE    = path/to/file.log                           (default: None, stdout only)

Usage:
    from core.logger import get_logger
    log = get_logger('mymodule')
    log.info('Hello %s', 'world')
"""
import json as _json
import logging
import logging.handlers
import os
import sys
from datetime import datetime, timezone

from core.conf import config


class _JsonFormatter(logging.Formatter):
    """Structured JSON log formatter for production/cloud environments."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            'timestamp': datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            entry['exception'] = self.formatException(record.exc_info)
        if hasattr(record, 'request_id'):
            entry['request_id'] = record.request_id
        return _json.dumps(entry, default=str)


class _TextFormatter(logging.Formatter):
    """Human-readable formatter for development."""

    def __init__(self) -> None:
        super().__init__(
            fmt='[%(asctime)s] %(levelname)s - %(name)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
        )


def _setup_logger() -> logging.Logger:
    """Configure the root 'nori' logger once."""
    logger = logging.getLogger('nori')

    if logger.handlers:
        return logger

    debug = config.get('DEBUG', False)
    level_name = os.environ.get('LOG_LEVEL', 'DEBUG' if debug else 'INFO').upper()
    level = getattr(logging, level_name, logging.INFO)
    logger.setLevel(level)

    log_format = os.environ.get('LOG_FORMAT', 'text').lower()
    formatter = _JsonFormatter() if log_format == 'json' else _TextFormatter()

    # Console handler (always)
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(formatter)
    logger.addHandler(console)

    # File handler (optional, with rotation)
    log_file = os.environ.get('LOG_FILE')
    if log_file:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding='utf-8',
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    logger.propagate = False
    return logger


_root_logger = _setup_logger()


def get_logger(name=None) -> logging.Logger:
    """
    Get a named child logger under the 'nori' namespace.

        log = get_logger('auth')    # -> nori.auth
        log = get_logger()          # -> nori
    """
    if name:
        return logging.getLogger(f'nori.{name}')
    return _root_logger
