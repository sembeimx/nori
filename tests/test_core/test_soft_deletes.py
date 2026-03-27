"""Tests for NoriSoftDeletes mixin."""
import pytest
from test_models import SamplePost


@pytest.fixture(autouse=True)
async def _clean_posts():
    """Clean up test posts before each test."""
    await SamplePost.all_objects.all().delete()
    yield


@pytest.mark.asyncio
async def test_soft_delete_sets_deleted_at():
    post = await SamplePost.create(title='To Delete')
    assert post.deleted_at is None
    assert post.is_trashed is False

    await post.delete()
    assert post.deleted_at is not None
    assert post.is_trashed is True


@pytest.mark.asyncio
async def test_soft_deleted_excluded_from_objects_manager():
    post = await SamplePost.create(title='Hidden')
    await post.delete()

    # Custom objects manager excludes soft-deleted
    visible = await SamplePost.objects.all()
    assert all(p.id != post.id for p in visible)


@pytest.mark.asyncio
async def test_restore_clears_deleted_at():
    post = await SamplePost.create(title='Restore Me')
    await post.delete()
    assert post.is_trashed is True

    await post.restore()
    assert post.deleted_at is None
    assert post.is_trashed is False


@pytest.mark.asyncio
async def test_force_delete_removes_permanently():
    post = await SamplePost.create(title='Gone Forever')
    post_id = post.id
    await post.force_delete()

    found = await SamplePost.all_objects.filter(id=post_id).first()
    assert found is None


@pytest.mark.asyncio
async def test_with_trashed_includes_deleted():
    active = await SamplePost.create(title='Active')
    deleted = await SamplePost.create(title='Deleted')
    await deleted.delete()

    all_posts = await SamplePost.all_objects.all()
    ids = [p.id for p in all_posts]
    assert active.id in ids
    assert deleted.id in ids


@pytest.mark.asyncio
async def test_only_trashed_returns_deleted_only():
    active = await SamplePost.create(title='Active')
    deleted = await SamplePost.create(title='Deleted')
    await deleted.delete()

    trashed = await SamplePost.trashed.all()
    ids = [p.id for p in trashed]
    assert deleted.id in ids
    assert active.id not in ids


@pytest.mark.asyncio
async def test_restore_idempotent_on_active_record():
    """Calling restore() on an already active record is a no-op."""
    post = await SamplePost.create(title='Already Active')
    assert post.deleted_at is None

    await post.restore()  # should not error or issue unnecessary queries
    assert post.deleted_at is None
