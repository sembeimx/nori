import warnings as _warnings

# Suppress Tortoise's `Module "X" has no models` RuntimeWarning. In Nori the
# user's `models` app is intentionally empty on fresh projects (and may stay
# empty in apps that only consume framework models). The warning isn't
# actionable; real registration bugs surface as failed queries or missing
# tables. Filter applies to in-process callers (serve, shell, tests). Aerich
# subprocesses get the same suppression via PYTHONWARNINGS in core.cli.
_warnings.filterwarnings(
    'ignore',
    message=r'Module ".+" has no models',
    category=RuntimeWarning,
)

from core.collection import NoriCollection, collect
from core.pagination import paginate
from core.logger import get_logger
from core.tasks import background, background_tasks, run_in_background
from core.cache import cache_get, cache_set, cache_delete, cache_flush, cache_response
from core.audit import audit, get_client_ip
from core.mail import send_mail, register_mail_driver, get_mail_drivers
from core.search import search, index_document, remove_document, register_search_driver, get_search_drivers
from core.queue import push

__all__ = [
    'NoriCollection', 'collect',
    'paginate',
    'get_logger',
    'background', 'background_tasks', 'run_in_background',
    'cache_get', 'cache_set', 'cache_delete', 'cache_flush', 'cache_response',
    'audit', 'get_client_ip',
    'send_mail', 'register_mail_driver', 'get_mail_drivers',
    'search', 'index_document', 'remove_document', 'register_search_driver', 'get_search_drivers',
    'push',
]
