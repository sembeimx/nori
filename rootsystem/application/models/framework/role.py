"""Framework Role model: named role with M2M to Permission, attached to users."""

from __future__ import annotations

from core.mixins.model import NoriModelMixin
from tortoise import fields
from tortoise.models import Model


class Role(NoriModelMixin, Model):
    """A role that groups permissions."""

    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=50, unique=True)
    permissions = fields.ManyToManyField(
        'framework.Permission',
        related_name='roles',
        through='role_permission',
    )

    class Meta:
        table = 'roles'
        # Stable order so paginate_cursor() yields contiguous, non-overlapping
        # windows. Without an explicit ordering Tortoise relies on the DB's
        # natural row order, which is unstable across pages.
        ordering = ['id']

    def __str__(self) -> str:
        return self.name
