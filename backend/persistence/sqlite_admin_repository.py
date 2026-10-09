"""SQL adapter. User changes, session revocation and audit share transactions."""
import time,uuid
from persistence.audit import append_audit,decode_audit
from persistence.repository import RepositoryConflict
SAFE_USER=('id','username','display_name','role_id','enabled','created_at','updated_at','last_login_at','created_by','updated_by')
def public_user(row):
    return {k:(bool(row[k]) if k=='enabled' else row[k]) for k in SAFE_USER} if row else None
class SQLiteAdminRepository:
    def __init__(self,commercial): self.commercial=commercial
    def find_user(self,username):
        with self.commercial.transaction() as u:
            row=u.db.execute('SELECT * FROM admin_users WHERE username=?',(username,)).fetchone()
            return dict(row) if row else None
    def list_users(self,limit=100,offset=0):
        with self.commercial.transaction() as u:
            return [public_user(r) for r in u.db.execute('SELECT * FROM admin_users ORDER BY created_at,id LIMIT ? OFFSET ?',(limit,offset))]
    def get_user(self,identifier):
        with self.commercial.transaction() as u:
            return public_user(self._user(u.db,identifier))
    def _user(self,db,identifier):
        row=db.execute('SELECT * FROM admin_users WHERE id=?',(identifier,)).fetchone()
        if not row: raise RepositoryConflict('Usuario no disponible')
        return dict(row)
    def create_user(self,data,actor,request_id,first=False):
        identifier,now=uuid.uuid4().hex,time.time()
        with self.commercial.transaction(write=True) as u:
            if first and u.db.execute('SELECT 1 FROM admin_users LIMIT 1').fetchone(): raise RepositoryConflict('La inicialización ya fue realizada')
            u.db.execute('INSERT INTO admin_users VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (identifier,data['username'],data['display_name'],data['password_hash'],data['role'],1,now,now,None,actor,actor))
            result=public_user(self._user(u.db,identifier))
            append_audit(u.db,actor,'user.create','users',identifier,None,result,request_id)
            return result
    def change_user(self,identifier,data,actor,request_id,expected=None):
        with self.commercial.transaction(write=True) as u:
            old=self._user(u.db,identifier)
            from domain.revision import check_revision
            check_revision(public_user(old), expected)
            if old['role_id']=='superadmin' and old['enabled'] and (not data['enabled'] or data['role']!='superadmin'):
                count=u.db.execute("SELECT count(*) FROM admin_users WHERE enabled=1 AND role_id='superadmin'").fetchone()[0]
                if count<=1: raise RepositoryConflict('Debe conservarse un superadmin habilitado')
            u.db.execute('UPDATE admin_users SET display_name=?,role_id=?,enabled=?,updated_at=?,updated_by=? WHERE id=?',
                (data['display_name'],data['role'],int(data['enabled']),time.time(),actor,identifier))
            if not data['enabled']:
                u.db.execute('UPDATE admin_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL',(time.time(),identifier))
            new=public_user(self._user(u.db,identifier))
            append_audit(u.db,actor,'user.update','users',identifier,old,new,request_id)
            return new
    def change_password(self,identifier,password_hash,actor,request_id):
        with self.commercial.transaction(write=True) as u:
            self._user(u.db,identifier)
            now=time.time()
            u.db.execute('UPDATE admin_users SET password_hash=?,updated_at=?,updated_by=? WHERE id=?',(password_hash,now,actor,identifier))
            u.db.execute('UPDATE admin_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL',(now,identifier))
            append_audit(u.db,actor,'user.password_changed','users',identifier,None,None,request_id)
    def open_session(self,user_id,password_hash,token_hash,csrf,now,inactivity,lifetime,request_id):
        with self.commercial.transaction(write=True) as u:
            user=self._user(u.db,user_id)
            # Close races with disable/password changes during expensive hashing.
            if not user['enabled'] or user['password_hash']!=password_hash: return False
            u.db.execute('DELETE FROM admin_sessions WHERE expires_at<=? OR absolute_expires_at<=? OR revoked_at IS NOT NULL',(now,now))
            sessions=u.db.execute('SELECT token_hash FROM admin_sessions WHERE user_id=? ORDER BY created_at DESC',(user_id,)).fetchall()
            for old in sessions[9:]: u.db.execute('DELETE FROM admin_sessions WHERE token_hash=?',(old[0],))
            u.db.execute('INSERT INTO admin_sessions VALUES(?,?,?,?,?,?,?,?,NULL)',(uuid.uuid4().hex,token_hash,user_id,csrf,now,now,now+inactivity,now+lifetime))
            u.db.execute('UPDATE admin_users SET last_login_at=? WHERE id=?',(now,user_id))
            append_audit(u.db,user_id,'auth.login','sessions',None,None,None,request_id,now)
            return True
    def authorize(self,token_hash,now,inactivity):
        with self.commercial.transaction(write=True) as u:
            row=u.db.execute('SELECT s.*,u.display_name,u.role_id,u.enabled FROM admin_sessions s JOIN admin_users u ON u.id=s.user_id WHERE s.token_hash=?',(token_hash,)).fetchone()
            if not row or not row['enabled'] or row['revoked_at'] is not None or min(row['expires_at'],row['absolute_expires_at'])<=now: return None
            u.db.execute('UPDATE admin_sessions SET updated_at=?,expires_at=? WHERE token_hash=?',(now,min(now+inactivity,row['absolute_expires_at']),token_hash))
            return dict(row)
    def revoke(self,token_hash,actor,request_id):
        with self.commercial.transaction(write=True) as u:
            # Idempotent: a revoked session remains unusable.
            cursor=u.db.execute('UPDATE admin_sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL',(time.time(),token_hash))
            if cursor.rowcount: append_audit(u.db,actor,'auth.logout','sessions',None,None,None,request_id)
    def revoke_user(self,user_id,actor,request_id):
        with self.commercial.transaction(write=True) as u:
            self._user(u.db,user_id)
            u.db.execute('UPDATE admin_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL',(time.time(),user_id))
            append_audit(u.db,actor,'sessions.revoke_all','users',user_id,None,None,request_id)
    def sessions(self,user_id):
        with self.commercial.transaction() as u:
            # Public session IDs are independent of opaque cookie credentials and their hashes.
            return [dict(r) for r in u.db.execute('SELECT id,created_at,updated_at,expires_at,absolute_expires_at,revoked_at FROM admin_sessions WHERE user_id=? ORDER BY created_at DESC',(user_id,))]
    def revoke_one(self,user_id,session_id,actor,request_id):
        with self.commercial.transaction(write=True) as u:
            changed=u.db.execute('UPDATE admin_sessions SET revoked_at=? WHERE user_id=? AND id=? AND revoked_at IS NULL',(time.time(),user_id,session_id)).rowcount
            if not changed: raise RepositoryConflict('Sesión no disponible')
            append_audit(u.db,actor,'sessions.revoke','users',user_id,None,None,request_id)
    def audit(self,limit=100,offset=0,filters=None):
        with self.commercial.transaction() as u:
            from persistence.audit import audit_where
            where,values=audit_where(filters,'a.')
            return [decode_audit(r) for r in u.db.execute('SELECT a.*,u.display_name AS actor_name FROM admin_audit_log a LEFT JOIN admin_users u ON u.id=a.actor_user_id '+where+' ORDER BY a.timestamp DESC,a.id DESC LIMIT ? OFFSET ?',(*values,limit,offset))]

    def actor_names(self,identifiers):
        if not identifiers: return {}
        with self.commercial.transaction() as u:
            marks=','.join('?' for _ in identifiers)
            return {row['id']:row['display_name'] for row in u.db.execute(f'SELECT id,display_name FROM admin_users WHERE id IN ({marks})',list(identifiers))}
