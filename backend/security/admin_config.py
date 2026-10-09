"""Validated settings independent of database and provider credentials."""
import os
from dataclasses import dataclass
@dataclass(frozen=True)
class AdminSettings:
    inactivity: int = 1800
    lifetime: int = 28800
    memory_cost: int = 65536
    time_cost: int = 3
    parallelism: int = 1
    password_min: int = 12
    account_limit: int = 5
    account_window: int = 300
    legacy_enabled: bool = True
    secure: bool = False
    cookie_name: str = 'lia_admin_session'
    def __post_init__(self):
        if not (60 <= self.inactivity <= self.lifetime <= 86400 and 19456 <= self.memory_cost <= 131072
                and 2 <= self.time_cost <= 6 and 1 <= self.parallelism <= 4 and 12 <= self.password_min <= 64
                and 1 <= self.account_limit <= 20 and 30 <= self.account_window <= 3600):
            raise ValueError('Invalid administrative security limits')
    @classmethod
    def from_env(cls):
        values={field:int(os.getenv(env,str(getattr(cls(),field)))) for field,env in {
            'inactivity':'ADMIN_SESSION_TTL_SECONDS','lifetime':'ADMIN_SESSION_LIFETIME_SECONDS',
            'memory_cost':'ADMIN_ARGON2_MEMORY_KIB','time_cost':'ADMIN_ARGON2_TIME_COST',
            'parallelism':'ADMIN_ARGON2_PARALLELISM','password_min':'ADMIN_PASSWORD_MIN_LENGTH',
            'account_limit':'ADMIN_LOGIN_ACCOUNT_LIMIT','account_window':'ADMIN_LOGIN_ACCOUNT_WINDOW'}.items()}
        legacy=os.getenv('ADMIN_LEGACY_TOKEN_ENABLED','true').lower()
        secure=os.getenv('ADMIN_COOKIE_SECURE','true' if os.getenv('APP_ENV')=='production' else 'false').lower()
        if legacy not in ('true','false') or secure not in ('true','false'): raise ValueError('Invalid admin boolean')
        if os.getenv('APP_ENV')=='production' and secure!='true': raise ValueError('Production requires Secure admin cookies')
        return cls(**values,legacy_enabled=legacy=='true',secure=secure=='true',cookie_name='__Secure-lia_admin_session' if secure=='true' else 'lia_admin_session')
