from __future__ import annotations

from core.mixins.model import NoriModelMixin
from tortoise import fields
from tortoise.models import Model


class AuditLog(NoriModelMixin, Model):
    """Tracks who did what and when."""

    protected_fields = ['ip_address']

    id = fields.IntField(primary_key=True)
    user_id = fields.IntField(null=True)
    action = fields.CharField(max_length=50)  # create/update/delete/login/logout/custom
    model_name = fields.CharField(max_length=100, null=True)
    record_id = fields.CharField(max_length=100, null=True)
    changes = fields.JSONField(null=True)  # {"field": {"before": ..., "after": ...}}
    ip_address = fields.CharField(max_length=45, null=True)
    request_id = fields.CharField(max_length=36, null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = 'audit_logs'
        ordering = ['-created_at']
        indexes = [
            ('action',),
            ('model_name',),
            ('user_id',),
            ('created_at',),
        ]
