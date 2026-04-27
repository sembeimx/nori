from __future__ import annotations

from core.mixins.model import NoriModelMixin
from tortoise import fields
from tortoise.models import Model


class Permission(NoriModelMixin, Model):
    """A granular permission (e.g. 'articles.edit')."""

    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=100, unique=True)
    description = fields.CharField(max_length=255, default='')

    class Meta:
        table = 'permissions'

    def __str__(self) -> str:
        return self.name
