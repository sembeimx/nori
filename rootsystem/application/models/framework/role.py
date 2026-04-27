from __future__ import annotations

from core.mixins.model import NoriModelMixin
from tortoise import fields
from tortoise.models import Model


class Role(NoriModelMixin, Model):
    """A role that groups permissions."""

    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=50, unique=True)
    permissions = fields.ManyToManyField(
        'framework.Permission', related_name='roles', through='role_permission',
    )

    class Meta:
        table = 'roles'

    def __str__(self) -> str:
        return self.name
