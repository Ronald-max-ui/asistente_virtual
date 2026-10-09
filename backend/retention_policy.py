"""Technical retention proposals only. No delete operation is implemented here."""
import os
from dataclasses import dataclass

def days(name,default):
    value=os.getenv(name,str(default) if default is not None else '')
    if not value:return None
    parsed=int(value)
    if not 1<=parsed<=36500:raise ValueError('Retention duration outside allowed range')
    return parsed
@dataclass(frozen=True)
class RetentionPolicy:
    sessions_days:int|None
    leads_days:int|None
    vouchers_days:int|None
    idempotency_days:int|None
    logs_days:int|None
    admin_users_days:int|None = None
    admin_audit_days:int|None = None
    lead_activity_days:int|None = None
    lead_tasks_days:int|None = None
    @classmethod
    def from_env(cls):
        return cls(days('RETENTION_SESSIONS_DAYS',2),days('RETENTION_LEADS_DAYS',None),
            days('RETENTION_VOUCHERS_DAYS',None),days('RETENTION_IDEMPOTENCY_DAYS',2),days('RETENTION_LOGS_DAYS',30),days('RETENTION_ADMIN_USERS_DAYS',None),days('RETENTION_ADMIN_AUDIT_DAYS',None),days('RETENTION_LEAD_ACTIVITY_DAYS',None),days('RETENTION_LEAD_TASKS_DAYS',None))
