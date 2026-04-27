from __future__ import annotations

from starlette.templating import Jinja2Templates

from core.auth.csrf import csrf_field
from core.conf import config
from core.http.flash import get_flashed_messages
from core.http.old import old

_templates: Jinja2Templates | None = None


def _get_templates() -> Jinja2Templates:
    global _templates
    if _templates is None:
        _templates = Jinja2Templates(directory=config.TEMPLATE_DIR)
        if config.get('DEBUG', False):
            _templates.env.auto_reload = True
        _templates.env.globals['csrf_field'] = csrf_field
        _templates.env.globals['get_flashed_messages'] = get_flashed_messages
        _templates.env.globals['old'] = old
    return _templates


class _LazyTemplates:
    """Proxy that defers Jinja2Templates creation until first use."""

    def __getattr__(self, name: str):
        return getattr(_get_templates(), name)


templates = _LazyTemplates()
