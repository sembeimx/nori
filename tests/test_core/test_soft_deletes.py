"""Tests for NoriSoftDeletes mixin."""

import pytest
from test_models import SamplePost


@pytest.fixture(autouse=True)
async def _clean_posts():
    """Clean up test posts before each test. Uses force_delete() because
    .delete() on the queryset is now soft (it sets deleted_at instead of
    physically removing rows) — soft cleanup would leave tombstones
    accumulating across tests."""
    await SamplePost.all_objects.all().force_delete()
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


# ---------------------------------------------------------------------------
# QuerySet-level delete (regression: bulk delete used to bypass the override)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_queryset_delete_is_soft_not_hard():
    """`await Model.objects.filter(...).delete()` must soft-delete via
    deleted_at, not issue a physical SQL DELETE. Tortoise's native
    QuerySet.delete() bypasses Model.delete() entirely, so the
    SoftDeleteQuerySet has to override delete() too — otherwise a single
    bulk call silently nukes rows the framework promised to keep."""
    a = await SamplePost.create(title='A')
    b = await SamplePost.create(title='B')

    affected = await SamplePost.objects.filter(title__in=['A', 'B']).delete()

    # Rows still exist physically, just marked as trashed
    found = await SamplePost.all_objects.filter(id__in=[a.id, b.id])
    assert len(found) == 2
    assert all(p.deleted_at is not None for p in found)
    # Tortoise's update() returns affected row count
    assert affected == 2


@pytest.mark.asyncio
async def test_queryset_force_delete_physically_removes_rows():
    """`force_delete()` on a queryset is the explicit hard-delete escape
    hatch — mirrors the per-instance API."""
    a = await SamplePost.create(title='A')
    b = await SamplePost.create(title='B')

    await SamplePost.objects.filter(title__in=['A', 'B']).force_delete()

    remaining = await SamplePost.all_objects.filter(id__in=[a.id, b.id])
    assert remaining == []


@pytest.mark.asyncio
async def test_queryset_delete_excluded_from_objects_manager_after():
    """A queryset-level soft delete must be invisible through the default
    `objects` manager just like the per-instance soft delete."""
    a = await SamplePost.create(title='A')
    b = await SamplePost.create(title='B')

    await SamplePost.objects.filter(id__in=[a.id, b.id]).delete()

    visible = await SamplePost.objects.all()
    visible_ids = {p.id for p in visible}
    assert a.id not in visible_ids
    assert b.id not in visible_ids


@pytest.mark.asyncio
async def test_all_objects_queryset_delete_is_also_soft():
    """`all_objects` includes both active and trashed rows — its bulk
    delete must also be soft, otherwise the manager becomes a hidden
    hard-delete escape hatch and the cleanup intent gets confused."""
    a = await SamplePost.create(title='A')
    b = await SamplePost.create(title='B')

    await SamplePost.all_objects.filter(id__in=[a.id, b.id]).delete()

    found = await SamplePost.all_objects.filter(id__in=[a.id, b.id])
    assert len(found) == 2
    assert all(p.deleted_at is not None for p in found)
