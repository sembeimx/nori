import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_home_page(client: AsyncClient):
    response = await client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

@pytest.mark.asyncio
async def test_auth_register(client: AsyncClient):
    # GET register page
    response = await client.get("/register")
    assert response.status_code == 200
    
    # Extract CSRF token (simplified for testing, we might need to parse HTML or use a session mocker, 
    # but for now we just verify the endpoint responds to GET correctly)
    assert 'name="_csrf_token"' in response.text

@pytest.mark.asyncio
async def test_auth_login_redirects(client: AsyncClient):
    # Profile should redirect to login if not authenticated
    response = await client.get("/profile", follow_redirects=False)
    assert response.status_code in (302, 303, 307)
    assert "/login" in response.headers["location"]
