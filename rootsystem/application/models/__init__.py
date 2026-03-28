# Register your models here — import AND register in the core registry.
#
# Framework models (AuditLog, Job, Permission, Role) live in models/framework/
# and are registered automatically below. Add your own application models after.

from models.framework import AuditLog, Permission, Role, Job

from core.registry import register_model

register_model('AuditLog', AuditLog)
register_model('Permission', Permission)
register_model('Role', Role)
register_model('Job', Job)
