from __future__ import annotations

from tortoise import fields
from tortoise.manager import Manager
from tortoise.models import Model
from tortoise.queryset import QuerySet


class SoftDeleteQuerySet(QuerySet):
    """QuerySet that auto-excludes records with deleted_at."""

    def _clone(self) -> SoftDeleteQuerySet:
        qs = super()._clone()
        qs.__class__ = self.__class__
        return qs


class SoftDeleteManager(Manager):
    """Default Manager: only active records."""

    def get_queryset(self) -> SoftDeleteQuerySet:
        return SoftDeleteQuerySet(self._model).filter(deleted_at__isnull=True)


class TrashedManager(Manager):
    """Manager for deleted records only."""

    def get_queryset(self) -> SoftDeleteQuerySet:
        return SoftDeleteQuerySet(self._model).filter(deleted_at__isnull=False)


class AllObjectsManager(Manager):
    """Manager without filters (includes everything)."""

    pass


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

    async def delete(self, using_db: object = None) -> None:
        """Soft delete: marks deleted_at with current timestamp."""
        from tortoise.timezone import now

        self.deleted_at = now()
        await self.save(update_fields=['deleted_at'], using_db=using_db)

    async def restore(self) -> None:
        """Restores a soft-deleted record. No-op if already active."""
        if self.deleted_at is None:
            return
        self.deleted_at = None
        await self.save(update_fields=['deleted_at'])

    async def force_delete(self, using_db: object = None) -> None:
        """Hard delete: permanently removes from the DB."""
        await super().delete(using_db=using_db)

    @property
    def is_trashed(self) -> bool:
        """True if the record is soft-deleted."""
        return self.deleted_at is not None

    @classmethod
    def with_trashed(cls) -> SoftDeleteQuerySet:
        """Returns QuerySet that includes deleted records."""
        return cls.all_objects.get_queryset()

    @classmethod
    def only_trashed(cls) -> SoftDeleteQuerySet:
        """Returns QuerySet with only deleted records."""
        return cls.trashed.get_queryset()
