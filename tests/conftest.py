import sys
import os

# Force test DB before any application import
os.environ['DB_ENGINE'] = 'sqlite'
os.environ['DB_NAME'] = ':memory:'

# Add rootsystem/application to Python path so imports work
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../rootsystem/application')))

import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from tortoise import Tortoise

from asgi import app
import settings


@pytest_asyncio.fixture(scope="session", autouse=True, loop_scope="session")
async def initialize_tests():
    await Tortoise.init(config=settings.TORTOISE_ORM)
    await Tortoise.generate_schemas()
    yield
    await Tortoise.close_connections()


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
