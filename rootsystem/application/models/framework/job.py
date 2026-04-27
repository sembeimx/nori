from __future__ import annotations

from core.mixins.model import NoriModelMixin
from tortoise import fields
from tortoise.models import Model


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
