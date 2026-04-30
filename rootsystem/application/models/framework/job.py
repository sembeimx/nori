"""Framework Job model: persistent queue entries (used when QUEUE_DRIVER=db)."""

from __future__ import annotations

from core.mixins.model import NoriModelMixin
from tortoise import fields
from tortoise.models import Model


class Job(NoriModelMixin, Model):
    """Persistent queue job entry.

    Inherits ``Model`` directly — **NOT** ``NoriSoftDeletes``. The worker
    hard-deletes successful jobs (``await job.delete()``) to keep the
    ``jobs`` table from accumulating processed rows indefinitely. Mixing
    in ``NoriSoftDeletes`` here would silently turn that delete into an
    ``UPDATE deleted_at = NOW()``, every successful job would stay in
    the table forever, the worker's polling query would slow linearly
    with table size, and eventually the database would choke. A regression
    test in ``tests/test_core/test_queue.py`` enforces this contract.
    """

    protected_fields = ['payload']

    id = fields.BigIntField(primary_key=True)
    queue = fields.CharField(max_length=50, default='default', index=True)
    payload: dict = fields.JSONField()
    attempts = fields.IntField(default=0)
    reserved_at = fields.DatetimeField(null=True)
    available_at = fields.DatetimeField(auto_now_add=True)
    failed_at = fields.DatetimeField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = 'jobs'
        ordering = ['available_at', 'id']
