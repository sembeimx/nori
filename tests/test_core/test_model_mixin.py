"""Tests for NoriModelMixin (to_dict, protected_fields).

Covers:
- Basic serialization (all fields, exclude list, empty exclude)
- Internal field exclusion (fields starting with _)
- protected_fields: automatic exclusion of sensitive fields
- protected_fields: include_protected=True to force-include them
- protected_fields: interaction with explicit exclude list
- Models without protected_fields work as before (backwards compatibility)
"""
import pytest
from test_models import SampleArticle, SampleUser


# ---------------------------------------------------------------------------
# Basic to_dict (backwards compatibility)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_to_dict_returns_all_fields():
    """Model without protected_fields returns all fields."""
    article = await SampleArticle.create(title='Hello', body='World')
    data = article.to_dict()
    assert data['title'] == 'Hello'
    assert data['body'] == 'World'
    assert 'id' in data


@pytest.mark.asyncio
async def test_to_dict_excludes_fields():
    """Explicit exclude list removes specified fields."""
    article = await SampleArticle.create(title='Secret', body='hidden')
    data = article.to_dict(exclude=['body'])
    assert 'title' in data
    assert 'body' not in data


@pytest.mark.asyncio
async def test_to_dict_excludes_internal_fields():
    """Fields starting with _ are always excluded."""
    article = await SampleArticle.create(title='Test', body='data')
    data = article.to_dict()
    for key in data:
        assert not key.startswith('_')


@pytest.mark.asyncio
async def test_to_dict_empty_exclude():
    """Empty exclude list has no effect."""
    article = await SampleArticle.create(title='A', body='B')
    data = article.to_dict(exclude=[])
    assert data['title'] == 'A'
    assert data['body'] == 'B'


# ---------------------------------------------------------------------------
# protected_fields
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_protected_fields_excluded_by_default():
    """Fields in protected_fields are excluded from to_dict() by default."""
    user = await SampleUser.create(username='alice', password_hash='h4sh', secret_token='tok')
    data = user.to_dict()
    assert data['username'] == 'alice'
    assert 'password_hash' not in data
    assert 'secret_token' not in data


@pytest.mark.asyncio
async def test_protected_fields_included_when_requested():
    """include_protected=True forces protected_fields into the output."""
    user = await SampleUser.create(username='bob', password_hash='h4sh', secret_token='tok')
    data = user.to_dict(include_protected=True)
    assert data['username'] == 'bob'
    assert data['password_hash'] == 'h4sh'
    assert data['secret_token'] == 'tok'


@pytest.mark.asyncio
async def test_protected_fields_combined_with_exclude():
    """Explicit exclude and protected_fields are merged."""
    user = await SampleUser.create(username='carol', password_hash='h', secret_token='t')
    data = user.to_dict(exclude=['username'])
    assert 'username' not in data
    assert 'password_hash' not in data
    assert 'secret_token' not in data
    assert 'id' in data


@pytest.mark.asyncio
async def test_model_without_protected_fields_unchanged():
    """Models that don't define protected_fields behave exactly as before."""
    article = await SampleArticle.create(title='Public', body='Content')
    data = article.to_dict()
    assert data['title'] == 'Public'
    assert data['body'] == 'Content'
