import logging
import sys
from settings import DEBUG

logger = logging.getLogger('nori')
logger.setLevel(logging.DEBUG if DEBUG else logging.INFO)

if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG if DEBUG else logging.INFO)
    formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s - %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def get_logger(name=None):
    if name:
        return logging.getLogger(f'nori.{name}')
    return logger
