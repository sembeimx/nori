"""Test models for mixin integration tests."""
from tortoise.models import Model
from tortoise import fields
from core.mixins.model import NoriModelMixin
from core.mixins.soft_deletes import NoriSoftDeletes
from core.mixins.tree import NoriTreeMixin


class SampleArticle(NoriModelMixin, Model):
    id = fields.IntField(pk=True)
    title = fields.CharField(max_length=100)
    body = fields.TextField(default='')

    class Meta:
        table = 'sample_article'


class SamplePost(NoriSoftDeletes):
    id = fields.IntField(pk=True)
    title = fields.CharField(max_length=200)

    class Meta:
        table = 'sample_post'


class SampleCategory(NoriTreeMixin):
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=100)
    parent = fields.ForeignKeyField(
        'models.SampleCategory', related_name='children_rel',
        null=True, default=None
    )

    class Meta:
        table = 'sample_category'
