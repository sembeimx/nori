"""Tests for /home — the default landing page controller."""

import pytest


@pytest.mark.asyncio
async def test_home_returns_200(client):
    """GET / renders home.html with a 200 status."""
    resp = await client.get('/')
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_home_renders_html(client):
    """Response is HTML, not JSON or plain text."""
    resp = await client.get('/')
    assert 'text/html' in resp.headers['content-type']


@pytest.mark.asyncio
async def test_home_includes_framework_metadata(client):
    """The default home page surfaces nori_version, python_version, and route_count.

    We don't pin the exact strings — the template can change — but the
    underlying context values must reach the response so a future
    refactor of the template still has the data wired up.
    """
    from core.version import __version__ as nori_version

    resp = await client.get('/')
    body = resp.text
    assert nori_version in body  # nori version surfaces somewhere on the page


@pytest.mark.asyncio
async def test_home_route_count_matches_registered_routes(client):
    """The route_count value in the context equals len(routes)."""
    from routes import routes

    resp = await client.get('/')
    # Loose check: the count should appear in the rendered output.
    # If templates change to omit the number, this can be tightened to
    # introspect the controller's context directly via dependency injection.
    assert str(len(routes)) in resp.text
