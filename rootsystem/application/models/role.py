from tortoise.models import Model
from tortoise import fields


class Role(Model):
    """A role that groups permissions."""

    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=50, unique=True)
    permissions = fields.ManyToManyField(
        'models.Permission', related_name='roles', through='role_permission',
    )

    class Meta:
        table = 'roles'

    def __str__(self) -> str:
        return self.name
