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

from core.audit import audit, get_client_ip
from core.cache import cache_delete, cache_flush, cache_get, cache_response, cache_set
from core.collection import NoriCollection, collect
from core.logger import get_logger
from core.mail import get_mail_drivers, register_mail_driver, send_mail
from core.pagination import paginate
from core.queue import push
from core.search import get_search_drivers, index_document, register_search_driver, remove_document, search
from core.tasks import background, background_tasks, run_in_background

__all__ = [
    'NoriCollection',
    'collect',
    'paginate',
    'get_logger',
    'background',
    'background_tasks',
    'run_in_background',
    'cache_get',
    'cache_set',
    'cache_delete',
    'cache_flush',
    'cache_response',
    'audit',
    'get_client_ip',
    'send_mail',
    'register_mail_driver',
    'get_mail_drivers',
    'search',
    'index_document',
    'remove_document',
    'register_search_driver',
    'get_search_drivers',
    'push',
]
