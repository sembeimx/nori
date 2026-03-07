"""Tests for NoriModelMixin (to_dict)."""
import pytest
from test_models import SampleArticle


@pytest.mark.asyncio
async def test_to_dict_returns_all_fields():
    article = await SampleArticle.create(title='Hello', body='World')
    data = article.to_dict()
    assert data['title'] == 'Hello'
    assert data['body'] == 'World'
    assert 'id' in data


@pytest.mark.asyncio
async def test_to_dict_excludes_fields():
    article = await SampleArticle.create(title='Secret', body='hidden')
    data = article.to_dict(exclude=['body'])
    assert 'title' in data
    assert 'body' not in data


@pytest.mark.asyncio
async def test_to_dict_excludes_internal_fields():
    article = await SampleArticle.create(title='Test', body='data')
    data = article.to_dict()
    for key in data:
        assert not key.startswith('_')


@pytest.mark.asyncio
async def test_to_dict_empty_exclude():
    article = await SampleArticle.create(title='A', body='B')
    data = article.to_dict(exclude=[])
    assert data['title'] == 'A'
    assert data['body'] == 'B'
