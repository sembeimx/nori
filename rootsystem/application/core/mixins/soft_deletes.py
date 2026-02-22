from __future__ import annotations

from tortoise.models import Model
from tortoise import fields
from tortoise.manager import Manager
from tortoise.queryset import QuerySet


class SoftDeleteQuerySet(QuerySet):
    """QuerySet que auto-excluye registros con deleted_at."""

    def _clone(self) -> SoftDeleteQuerySet:
        qs = super()._clone()
        qs.__class__ = self.__class__
        return qs


class SoftDeleteManager(Manager):
    """Manager predeterminado: solo registros activos."""

    def get_queryset(self) -> SoftDeleteQuerySet:
        return SoftDeleteQuerySet(self._model).filter(deleted_at__isnull=True)


class TrashedManager(Manager):
    """Manager para solo registros eliminados."""

    def get_queryset(self) -> SoftDeleteQuerySet:
        return SoftDeleteQuerySet(self._model).filter(deleted_at__isnull=False)


class AllObjectsManager(Manager):
    """Manager sin filtros (incluye todo)."""
    pass


class NoriSoftDeletes(Model):
    """
    Mixin para soft deletes en Tortoise ORM.

        class Post(NoriSoftDeletes):
            title = fields.CharField(max_length=200)

            class Meta:
                table = 'post'

        post = await Post.get(id=1)
        await post.delete()              # SET deleted_at = NOW()
        await post.restore()             # SET deleted_at = NULL
        await post.force_delete()        # DELETE real

        # Queries auto-excluyen soft-deleted
        posts = await Post.filter().all()                        # solo activos
        posts = await Post.with_trashed().all()                  # todos
        posts = await Post.only_trashed().all()                  # solo eliminados
    """

    deleted_at = fields.DatetimeField(null=True, default=None)

    # Managers
    objects: SoftDeleteManager = SoftDeleteManager()         # default: excluye eliminados
    all_objects: AllObjectsManager = AllObjectsManager()     # incluye todo
    trashed: TrashedManager = TrashedManager()               # solo eliminados

    class Meta:
        abstract = True

    async def delete(self, using_db: object = None) -> None:
        """Soft delete: marca deleted_at con timestamp actual."""
        from tortoise.timezone import now
        self.deleted_at = now()
        await self.save(update_fields=['deleted_at'], using_db=using_db)

    async def restore(self) -> None:
        """Restaura un registro soft-deleted."""
        self.deleted_at = None
        await self.save(update_fields=['deleted_at'])

    async def force_delete(self, using_db: object = None) -> None:
        """Hard delete: elimina permanentemente de la DB."""
        await super().delete(using_db=using_db)

    @property
    def is_trashed(self) -> bool:
        """True si el registro esta soft-deleted."""
        return self.deleted_at is not None

    @classmethod
    def with_trashed(cls) -> SoftDeleteQuerySet:
        """Retorna QuerySet que incluye registros eliminados."""
        return cls.all_objects.get_queryset()

    @classmethod
    def only_trashed(cls) -> SoftDeleteQuerySet:
        """Retorna QuerySet con solo registros eliminados."""
        return cls.trashed.get_queryset()
