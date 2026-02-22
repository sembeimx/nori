from starlette.templating import Jinja2Templates
import settings
from core.auth.csrf import csrf_field
from core.http.flash import get_flashed_messages

templates = Jinja2Templates(directory=settings.TEMPLATE_DIR)
if settings.DEBUG:
    templates.env.auto_reload = True

templates.env.globals['csrf_field'] = csrf_field
templates.env.globals['get_flashed_messages'] = get_flashed_messages
