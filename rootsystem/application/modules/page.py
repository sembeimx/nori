import sys
from starlette.requests import Request
from core.jinja import templates


class PageController:

    async def home(self, request: Request):
        python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        
        return templates.TemplateResponse(request, 'home.html', {
            'user_id': request.session.get('user_id'),
            'nori_version': '1.0.0',
            'python_version': python_version
        })
