# Register your models here — import AND register in the core registry
from models.audit_log import AuditLog
from models.permission import Permission
from models.role import Role
from models.job import Job

from core.registry import register_model

register_model('AuditLog', AuditLog)
register_model('Permission', Permission)
register_model('Role', Role)
register_model('Job', Job)
