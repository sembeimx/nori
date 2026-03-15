from tortoise.models import Model
from tortoise import fields


class AuditLog(Model):
    """Tracks who did what and when."""

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
