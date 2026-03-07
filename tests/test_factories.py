"""Tests for test factories."""
import pytest
from factories import make_article, make_post, make_category, reset_counters
from test_models import SampleArticle, SamplePost, SampleCategory


@pytest.fixture(autouse=True)
async def _clean():
    reset_counters()
    await SampleArticle.all().delete()
    await SamplePost.all_objects.all().delete()
    await SampleCategory.all().delete()
    yield


@pytest.mark.asyncio
async def test_make_article_defaults():
    article = await make_article()
    assert article.id is not None
    assert article.title.startswith('Article ')


@pytest.mark.asyncio
async def test_make_article_overrides():
    article = await make_article(title='Custom', body='Custom body')
    assert article.title == 'Custom'
    assert article.body == 'Custom body'


@pytest.mark.asyncio
async def test_make_post_defaults():
    post = await make_post()
    assert post.id is not None
    assert post.title.startswith('Post ')
    assert post.deleted_at is None


@pytest.mark.asyncio
async def test_make_category_defaults():
    cat = await make_category()
    assert cat.id is not None
    assert cat.name.startswith('Category ')


@pytest.mark.asyncio
async def test_make_category_with_parent():
    root = await make_category(name='Root')
    child = await make_category(name='Child', parent_id=root.id)
    assert child.parent_id == root.id


@pytest.mark.asyncio
async def test_factories_generate_unique_defaults():
    a1 = await make_article()
    a2 = await make_article()
    assert a1.title != a2.title
