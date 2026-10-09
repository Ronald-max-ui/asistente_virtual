"""Administrative identity orchestration; no SQL or HTTP dependencies."""
import hashlib,secrets,time,re
from threading import BoundedSemaphore
from argon2 import PasswordHasher,Type
from argon2.exceptions import VerificationError,InvalidHashError
from security.admin_config import AdminSettings
from security.admin_policy import AdminPrincipal
from security.rate_limit import MemoryRateLimitStore
from domain.admin import normalize_username
from domain.errors import DomainError
class AdminError(DomainError):
    def __init__(self,code,status,retry=None):
        super().__init__(code,status)
        self.retry=retry
def digest(value): return hashlib.sha256(value.encode()).hexdigest()
class AdminService:
    def __init__(self,repository,configuration=None,clock=time.time):
        self.repository=repository
        self.settings=configuration or AdminSettings.from_env()
        self.clock=clock
        self.hasher=PasswordHasher(time_cost=self.settings.time_cost,memory_cost=self.settings.memory_cost,parallelism=self.settings.parallelism,type=Type.ID)
        self.attempts=MemoryRateLimitStore(10000)
        self.capacity=BoundedSemaphore(2)
        self._dummy=None
    def _slot(self):
        if not self.capacity.acquire(blocking=False): raise AdminError('admin_capacity',429,retry=2)
    def password_hash(self,password,username=''):
        if (not self.settings.password_min<=len(password)<=256 or len(set(password))<6 or len(set(password.casefold()))<5
                or bool(re.fullmatch(r'(?:password|contrase[nñ]a|admin|qwerty|letmein|welcome)[0-9!@#$%^&*._-]*',password.casefold()))
                or password.casefold() in ('password1234','contraseña123','adminadmin123','changeme123456')
                or (username and normalize_username(username) in password.casefold())):
            raise AdminError('weak_password',422)
        self._slot()
        try: return self.hasher.hash(password)
        finally: self.capacity.release()
    def create(self,data,actor,request_id,first=False):
        if first and data.role!='superadmin': raise AdminError('admin_bootstrap_role',422)
        return self.repository.create_user(dict(username=data.username,display_name=data.display_name,role=data.role,
            password_hash=self.password_hash(data.password.get_secret_value(),data.username)),actor,request_id,first)
    def login(self,username,password,request_id):
        key=digest(username)
        retry=self.attempts.consume(key,self.settings.account_limit,self.settings.account_window)
        if retry: raise AdminError('admin_login_limited',429,retry=retry)
        self._slot()
        try:
            if self._dummy is None: self._dummy=self.hasher.hash(secrets.token_urlsafe(32))
            user=self.repository.find_user(username)
            try: valid=self.hasher.verify(user['password_hash'] if user else self._dummy,password)
            except (VerificationError,InvalidHashError): valid=False
            if not valid or not user or not user['enabled']: raise AdminError('admin_credentials',401)
            token,csrf=secrets.token_urlsafe(32),secrets.token_urlsafe(32)
            if not self.repository.open_session(user['id'],user['password_hash'],digest(token),csrf,self.clock(),self.settings.inactivity,self.settings.lifetime,request_id):
                raise AdminError('admin_credentials',401)
            return token
        finally: self.capacity.release()
    def session(self,token):
        if not token or len(token)>128: raise AdminError('admin_session',401)
        row=self.repository.authorize(digest(token),self.clock(),self.settings.inactivity)
        if not row: raise AdminError('admin_session',401)
        return AdminPrincipal(row['user_id'],row['display_name'],row['role_id'],digest(token)),row['csrf']
    def change_password(self,identifier,password,actor,request_id):
        hashed=self.password_hash(password)
        self.repository.change_password(identifier,hashed,actor,request_id)

    def audit(self,runtime_repository,limit,offset,filters=None):
        records=self.repository.audit(limit+offset,filters=filters)+runtime_repository.admin_audit(limit+offset,filters=filters)
        page=sorted(records,key=lambda r:(r['timestamp'],r['id']),reverse=True)[offset:offset+limit]
        names=self.repository.actor_names({r['actor_user_id'] for r in page})
        return [{**row,'actor_name':names.get(row['actor_user_id'])} for row in page]
