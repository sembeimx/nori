"""NoriSoftDeletes mixin: logical deletion via deleted_at timestamp."""

from __future__ import annotations

from typing import Any

from tortoise import fields
from tortoise.manager import Manager
from tortoise.models import Model
from tortoise.queryset import QuerySet

# Tortoise's QuerySet/Model stubs do not preserve subclass identity through
# .filter()/._clone() (the chainables return the base QuerySet type), and
# Model.save/delete declare using_db with a tortoise-internal type that this
# module cannot reference without coupling to private API. The # type: ignore
# blocks below silence those stub gaps; runtime behavior is correct because
# qs.__class__ is rebound to the subclass.


class SoftDeleteQuerySet(QuerySet):
    """QuerySet that auto-excludes records with deleted_at and routes
    bulk ``.delete()`` through the soft-delete path."""

    def _clone(self) -> SoftDeleteQuerySet:
        qs = super()._clone()
        qs.__class__ = self.__class__
        return qs  # type: ignore[return-value]

    async def delete(self) -> int:  # type: ignore[override]
        """Soft delete: set ``deleted_at = NOW()`` on every matching row.

        Tortoise's native ``QuerySet.delete()`` issues a raw SQL DELETE
        without calling ``Model.delete()``, so without this override the
        mixin's per-instance soft-delete is silently bypassed by any
        bulk ``await Model.filter(...).delete()`` and rows are
        physically removed. Use :meth:`force_delete` when a hard delete
        is what you actually want.
        """
        from tortoise.timezone import now

        return await self.update(deleted_at=now())

    def force_delete(self) -> Any:
        """Hard delete: bypass the soft-delete override and issue a real
        SQL DELETE for every matching row. Awaitable, returns whatever
        Tortoise's native ``QuerySet.delete()`` returns."""
        return super().delete()


class SoftDeleteManager(Manager):
    """Default Manager: only active records."""

    def get_queryset(self) -> SoftDeleteQuerySet:
        return SoftDeleteQuerySet(self._model).filter(deleted_at__isnull=True)  # type: ignore[return-value]


class TrashedManager(Manager):
    """Manager for deleted records only."""

    def get_queryset(self) -> SoftDeleteQuerySet:
        return SoftDeleteQuerySet(self._model).filter(deleted_at__isnull=False)  # type: ignore[return-value]


class AllObjectsManager(Manager):
    """Manager without filters (includes active + deleted).

    Returns the soft-delete queryset so bulk ``.delete()`` through this
    manager is also soft — call ``.force_delete()`` when physical
    removal is intended.
    """

    def get_queryset(self) -> SoftDeleteQuerySet:
        return SoftDeleteQuerySet(self._model)  # type: ignore[return-value]


class NoriSoftDeletes(Model):
    """
    Mixin for soft deletes in Tortoise ORM.

        class Post(NoriSoftDeletes):
            title = fields.CharField(max_length=200)

            class Meta:
                table = 'post'

        post = await Post.get(id=1)
        await post.delete()              # SET deleted_at = NOW()
        await post.restore()             # SET deleted_at = NULL
        await post.force_delete()        # real DELETE

        # Queries auto-exclude soft-deleted
        posts = await Post.filter().all()                        # only active
        posts = await Post.with_trashed().all()                  # all
        posts = await Post.only_trashed().all()                  # only deleted
    """

    deleted_at = fields.DatetimeField(null=True, default=None)

    # Managers
    objects: SoftDeleteManager = SoftDeleteManager()  # default: excludes deleted
    all_objects: AllObjectsManager = AllObjectsManager()  # includes everything
    trashed: TrashedManager = TrashedManager()  # only deleted

    class Meta:
        abstract = True

    async def delete(self, using_db: Any = None) -> None:
        """Soft delete: marks deleted_at with current timestamp."""
        from tortoise.timezone import now

        self.deleted_at = now()
        await self.save(update_fields=['deleted_at'], using_db=using_db)

    async def restore(self) -> None:
        """Restores a soft-deleted record. No-op if already active."""
        if self.deleted_at is None:
            return
        self.deleted_at = None  # type: ignore[assignment]  # field is null=True
        await self.save(update_fields=['deleted_at'])

    async def force_delete(self, using_db: Any = None) -> None:
        """Hard delete: permanently removes from the DB."""
        await super().delete(using_db=using_db)

    @property
    def is_trashed(self) -> bool:
        """True if the record is soft-deleted."""
        return self.deleted_at is not None

    @classmethod
    def with_trashed(cls) -> SoftDeleteQuerySet:
        """Returns QuerySet that includes deleted records."""
        return cls.all_objects.get_queryset()  # type: ignore[return-value]

    @classmethod
    def only_trashed(cls) -> SoftDeleteQuerySet:
        """Returns QuerySet with only deleted records."""
        return cls.trashed.get_queryset()
