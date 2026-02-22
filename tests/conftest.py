import asyncio
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from tortoise import Tortoise

# Add rootsystem/application to Python path so imports work
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../rootsystem/application')))

from asgi import app

# Force DB_ENGINE early
os.environ['DB_ENGINE'] = 'sqlite'
os.environ['DB_NAME'] = ':memory:'

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session", autouse=True)
async def initialize_tests():
    await Tortoise.init(
        db_url="sqlite://:memory:",
        modules={"models": ["models.user", "models.product"]}
    )
    await Tortoise.generate_schemas()
    yield
    await Tortoise.close_connections()

@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
