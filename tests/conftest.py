import sys
import os

# Force test DB before any application import
os.environ['DB_ENGINE'] = 'sqlite'
os.environ['DB_NAME'] = ':memory:'

# Add rootsystem/application and tests/ to Python path
_tests_dir = os.path.dirname(__file__)
_app_dir = os.path.abspath(os.path.join(_tests_dir, '../rootsystem/application'))
sys.path.insert(0, _app_dir)
sys.path.insert(0, _tests_dir)

import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from tortoise import Tortoise

from asgi import app
import settings


@pytest_asyncio.fixture(scope="session", autouse=True, loop_scope="session")
async def initialize_tests():
    config = {
        'connections': settings.TORTOISE_ORM['connections'],
        'apps': {
            'framework': {
                'models': ['models.framework'],
                'default_connection': 'default',
            },
            'models': {
                'models': ['models', 'test_models'],
                'default_connection': 'default',
            },
        },
    }
    await Tortoise.init(config=config)
    await Tortoise.generate_schemas()
    yield
    await Tortoise.close_connections()


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
