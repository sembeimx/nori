from __future__ import annotations

from tortoise.models import Model
from tortoise import fields

from core.mixins.model import NoriModelMixin


class Job(NoriModelMixin, Model):
    """Persistent queue job entry."""

    protected_fields = ['payload']

    id = fields.BigIntField(primary_key=True)
    queue = fields.CharField(max_length=50, default='default', index=True)
    payload = fields.JSONField()
    attempts = fields.IntField(default=0)
    reserved_at = fields.DatetimeField(null=True)
    available_at = fields.DatetimeField(auto_now_add=True)
    failed_at = fields.DatetimeField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = 'jobs'
        ordering = ['available_at', 'id']
