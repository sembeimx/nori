import asyncio
import sys
import os

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from tortoise import Tortoise

# Add rootsystem/application to Python path so imports work
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../rootsystem/application')))

# Force DB_ENGINE early
os.environ['DB_ENGINE'] = 'sqlite'
os.environ['DB_NAME'] = ':memory:'

from asgi import app

@pytest_asyncio.fixture(scope="session", autouse=True, loop_scope="session")
async def initialize_tests():
    await Tortoise.init(
        db_url="sqlite://:memory:",
        modules={"models": ["models"]}
    )
    await Tortoise.generate_schemas()
    yield
    await Tortoise.close_connections()

@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
