"""Separate runtime DB; transactional ownership and commercial associations.

No audio, provider responses, credentials in plaintext, or complete prompt logs.
All ownership/idempotency checks are made inside BEGIN IMMEDIATE transactions.
"""
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager, closing
from pathlib import Path
from persistence.runtime_repository import RuntimeConflict
from domain.idempotency import fingerprint
from persistence.sqlite_backup import backup_sqlite

SCHEMA = '''
CREATE TABLE IF NOT EXISTS sessions(
 session_id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, created_at REAL NOT NULL,
 updated_at REAL NOT NULL, expires_at REAL NOT NULL, absolute_expires_at REAL NOT NULL,
 active_request_id TEXT, active_until REAL, persona TEXT CHECK(persona IN ('info','sales')),
 funnel_stage TEXT NOT NULL DEFAULT 'discovery' CHECK(funnel_stage IN ('discovery','value','lead_captured','closing')),
 lead_id TEXT REFERENCES leads(lead_id), shown_media TEXT NOT NULL DEFAULT '[]', expired INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS turns(
 id INTEGER PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(session_id),
 request_id TEXT NOT NULL UNIQUE, question TEXT NOT NULL, answer TEXT NOT NULL, created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS turns_session ON turns(session_id,id);
CREATE TABLE IF NOT EXISTS leads(
 lead_id TEXT PRIMARY KEY, session_id TEXT REFERENCES sessions(session_id), name TEXT NOT NULL,
 whatsapp TEXT NOT NULL, program TEXT, modality TEXT, origin TEXT NOT NULL,
 notes TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS vouchers(
 voucher_id TEXT PRIMARY KEY, lead_id TEXT REFERENCES leads(lead_id), session_id TEXT REFERENCES sessions(session_id),
 program TEXT NOT NULL, modality TEXT, shift TEXT, concept TEXT NOT NULL, amount TEXT NOT NULL,
 currency TEXT NOT NULL, campaign_id TEXT, campaign TEXT, file_reference TEXT NOT NULL UNIQUE,
 created_at REAL NOT NULL, updated_at REAL NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending_review' CHECK(status IN ('pending_review','approved','rejected')));
CREATE TABLE IF NOT EXISTS operations(
 scope TEXT NOT NULL, kind TEXT NOT NULL, key TEXT NOT NULL, fingerprint TEXT NOT NULL,
 result TEXT NOT NULL, created_at REAL NOT NULL, PRIMARY KEY(scope,kind,key));
CREATE TABLE IF NOT EXISTS voucher_reviews(
 voucher_id TEXT PRIMARY KEY REFERENCES vouchers(voucher_id),review_note TEXT NOT NULL,
 reviewed_by TEXT NOT NULL,reviewed_at REAL NOT NULL);

'''



class SQLiteRuntimeRepository:
    def __init__(self, path, inactivity=1800, lifetime=86400, max_turns=12,
                 max_chars=24000, lease=120, clock=time.time):
        if not (1 <= max_turns <= 100 and 2000 <= max_chars <= 200000
                and 30 <= inactivity <= lifetime <= 2592000 and 10 <= lease <= 600):
            raise ValueError('Invalid runtime limits')
        self.path = Path(path).resolve()
        public = Path(__file__).resolve().parents[1] / 'static'
        if self.path.is_relative_to(public.resolve()):
            raise ValueError('Runtime database must be private')
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.inactivity, self.lifetime = inactivity, lifetime
        self.max_turns, self.max_chars, self.lease, self.clock = max_turns, max_chars, lease, clock
        with closing(self.connect()) as db:
            if db.execute('PRAGMA user_version').fetchone()[0] > 3:
                raise ValueError('Unsupported runtime schema')
            from persistence.admin_schema import SCHEMA as ADMIN_SCHEMA
            audit_schema='CREATE TABLE IF NOT EXISTS admin_audit_log' + ADMIN_SCHEMA.split('CREATE TABLE IF NOT EXISTS admin_audit_log',1)[1]
            from persistence.lead_schema import SCHEMA as LEAD_SCHEMA,seed
            db.executescript('BEGIN IMMEDIATE;\n' + SCHEMA + audit_schema + LEAD_SCHEMA)
            for lead in db.execute('SELECT lead_id,whatsapp,created_at FROM leads'):seed(db,lead['lead_id'],lead['whatsapp'],lead['created_at'])
            db.execute('PRAGMA user_version=3')
            db.commit()
            db.execute('PRAGMA journal_mode=WAL')
        if os.name != 'nt': self.path.chmod(0o600)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA synchronous=FULL')
        return db

    @contextmanager
    def transaction(self):
        db = self.connect()
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally: db.close()

    def _session(self, db, sid):
        row = db.execute('SELECT * FROM sessions WHERE session_id=?', (sid,)).fetchone()
        if not row: raise RuntimeConflict('session_not_found', 401)
        if row['expired'] or min(row['expires_at'], row['absolute_expires_at']) <= self.clock():
            raise RuntimeConflict('session_expired', 410)
        return dict(row)

    def create_session(self, sid, token_hash):
        now = self.clock()
        with self.transaction() as db:
            if db.execute('SELECT 1 FROM sessions WHERE session_id=?', (sid,)).fetchone():
                raise RuntimeConflict('session_exists')
            db.execute('INSERT INTO sessions(session_id,token_hash,created_at,updated_at,expires_at,absolute_expires_at) VALUES(?,?,?,?,?,?)',
                       (sid, token_hash, now, now, now+self.inactivity, now+self.lifetime))
        return sid

    def authorize(self, sid, token_hash):
        import hmac
        with self.transaction() as db:
            row = self._session(db, sid)
            if not hmac.compare_digest(row['token_hash'], token_hash):
                raise RuntimeConflict('session_unauthorized', 401)
        return row

    def snapshot(self, sid):
        with self.transaction() as db:
            row = self._session(db, sid)
            turns = db.execute('SELECT question,answer FROM turns WHERE session_id=? ORDER BY id', (sid,)).fetchall()
        row['history'] = [message for t in turns for message in
                          ({'role':'user','content':t['question']}, {'role':'assistant','content':t['answer']})]
        row['shown_media'] = json.loads(row['shown_media'])
        row['lead_submitted'] = bool(row['lead_id'])
        return row

    def _replay(self, db, scope, kind, key, digest):
        if not key: return None
        row = db.execute('SELECT * FROM operations WHERE scope=? AND kind=? AND key=?', (scope,kind,key)).fetchone()
        if row:
            if row['fingerprint'] != digest: raise RuntimeConflict('idempotency_conflict')
            return json.loads(row['result'])

    def _record(self, db, scope, kind, key, digest, result):
        if key:
            db.execute('INSERT INTO operations VALUES(?,?,?,?,?,?)',
                       (scope, kind, key, digest, json.dumps(result), self.clock()))

    def begin(self, sid, persona, replace=False, key=None):
        now, rid = self.clock(), uuid.uuid4().hex
        with self.transaction() as db:
            row = self._session(db, sid)
            if key and self._replay(db, sid, 'chat', key, key):
                raise RuntimeConflict('interaction_already_processed')
            old = row['active_request_id']
            if old and row['active_until'] > now and not replace:
                raise RuntimeConflict('session_busy')
            # A claimed key is never reused, including cancelled/incomplete delivery.
            self._record(db, sid, 'chat', key, key, {'request_id':rid})
            db.execute('UPDATE sessions SET active_request_id=?,active_until=?,persona=?,updated_at=?,expires_at=? WHERE session_id=?',
                       (rid, now+self.lease, persona, now, min(now+self.inactivity,row['absolute_expires_at']), sid))
        return rid, old

    def _current(self, db, sid, rid):
        row = self._session(db, sid)
        if row['active_request_id'] != rid or row['active_until'] <= self.clock():
            raise RuntimeConflict('interaction_cancelled')
        return row

    def current(self, sid, rid):
        with self.transaction() as db: self._current(db, sid, rid)
        return True

    def finish(self, sid, rid, question, answer, actions):
        with self.transaction() as db:
            row = self._current(db, sid, rid)
            if question:
                db.execute('INSERT INTO turns(session_id,request_id,question,answer,created_at) VALUES(?,?,?,?,?)',
                           (sid,rid,question,answer,self.clock()))
            turns = db.execute('SELECT id,length(question)+length(answer) AS size FROM turns WHERE session_id=? ORDER BY id DESC', (sid,)).fetchall()
            size = 0
            for index, turn in enumerate(turns):
                size += turn['size']
                if index >= self.max_turns or size > self.max_chars:
                    db.execute('DELETE FROM turns WHERE id=?', (turn['id'],))
            shown = json.loads(row['shown_media'])
            for action in actions:
                if action['type']=='show_gallery' and action['resource_id'] not in shown: shown.append(action['resource_id'])
            stage = row['funnel_stage']
            if question and stage=='discovery': stage='value'
            if row['lead_id'] and any(a['type']=='show_payment' for a in actions): stage='closing'
            db.execute('UPDATE sessions SET shown_media=?,funnel_stage=?,updated_at=? WHERE session_id=?',
                       (json.dumps(shown[-32:]),stage,self.clock(),sid))

    def release(self, sid, rid):
        with self.transaction() as db:
            db.execute('UPDATE sessions SET active_request_id=NULL,active_until=NULL WHERE session_id=? AND active_request_id=?', (sid,rid))

    def cancel(self, sid, rid=None, reset=False, key=None):
        digest = fingerprint({'request_id':rid,'reset':reset})
        with self.transaction() as db:
            row = self._session(db,sid)
            replay = self._replay(db,sid,'reset' if reset else 'cancel',key,digest)
            if replay is not None: return replay, None
            old = row['active_request_id']
            # Targeted cancellation cannot invalidate a more recent request.
            if rid and old != rid: old = None
            if old or reset:
                db.execute('UPDATE sessions SET active_request_id=NULL,active_until=NULL,updated_at=?,expires_at=? WHERE session_id=?',
                           (self.clock(), min(self.clock()+self.inactivity,row['absolute_expires_at']),sid))
            if reset:
                db.execute('DELETE FROM turns WHERE session_id=?', (sid,))
                db.execute("UPDATE sessions SET shown_media='[]',funnel_stage=? WHERE session_id=?",
                           ('lead_captured' if row['lead_id'] else 'discovery',sid))
            result={'status':'ok','cancelled':bool(old),'reset':reset}
            self._record(db,sid,'reset' if reset else 'cancel',key,digest,result)
        return result, old

    def save_lead(self, sid, data, key=None):
        scope, digest = sid or 'anonymous', fingerprint(data)
        with self.transaction() as db:
            row = self._session(db,sid) if sid else None
            replay=self._replay(db,scope,'lead',key,digest)
            if replay is not None: return replay
            # A session represents one prospect; updates of identity require a new conversation identity.
            if row and row['lead_id']: raise RuntimeConflict('lead_already_associated')
            identifier, now = uuid.uuid4().hex, self.clock()
            db.execute('INSERT INTO leads VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (identifier,sid,data['name'],data['whatsapp'],data.get('program'),data.get('modality'),
                        data['origin'],data.get('notes',''),now,now))
            from persistence.lead_schema import seed
            seed(db,identifier,data['whatsapp'],now)
            if sid:
                db.execute("UPDATE sessions SET lead_id=?,funnel_stage='lead_captured',updated_at=?,expires_at=? WHERE session_id=?",
                           (identifier,now,min(now+self.inactivity,row['absolute_expires_at']),sid))
            result={'status':'ok','lead_id':identifier,'message':'Datos registrados correctamente.'}
            self._record(db,scope,'lead',key,digest,result)
            return result

    def save_voucher(self, sid, tariff, digest, key, write_file, remove_file, expected_lead=None, check_association=False):
        scope=sid or 'anonymous'
        reference=None
        try:
            with self.transaction() as db:
                row=self._session(db,sid) if sid else None
                replay=self._replay(db,scope,'voucher',key,digest)
                if replay is not None: return replay
                lead_id=row['lead_id'] if row else None
                if (check_association or expected_lead) and expected_lead != lead_id:
                    raise RuntimeConflict('lead_mismatch')
                if lead_id:
                    lead=db.execute('SELECT program,modality FROM leads WHERE lead_id=?',(lead_id,)).fetchone()
                    if (lead['program'] and lead['program'] != tariff['program']) or (lead['modality'] and lead['modality'] != tariff['modality']):
                        raise RuntimeConflict('lead_program_mismatch')
                identifier, reference=write_file()
                now=self.clock()
                db.execute('INSERT INTO vouchers VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           (identifier,lead_id,sid,tariff['program'],tariff['modality'],tariff['shift'],tariff['concept'],
                            tariff['amount'],tariff['currency'],tariff.get('campaign_id'),tariff['campaign'],reference,now,now,'pending_review'))
                if lead_id:
                    from persistence.lead_schema import activity
                    activity(db,lead_id,'voucher_received',None,now,data={'voucher_id':identifier})
                result={'status':'ok','voucher_id':identifier,'review_status':'pending_review',
                        'message':'Comprobante recibido y pendiente de revisión.'}
                self._record(db,scope,'voucher',key,digest,result)
                if sid and lead_id: db.execute("UPDATE sessions SET funnel_stage='closing' WHERE session_id=?",(sid,))
                return result
        except BaseException:
            if reference: remove_file(reference)
            raise

    def get_record(self, kind, identifier):
        if kind not in ('leads','vouchers'): raise ValueError('Invalid record type')
        column='lead_id' if kind=='leads' else 'voucher_id'
        with closing(self.connect()) as db:
            row=db.execute(f'SELECT * FROM {kind} WHERE {column}=?',(identifier,)).fetchone()
            return dict(row) if row else None

    def cleanup(self):
        with self.transaction() as db:
            now=self.clock()
            rows=db.execute('SELECT session_id,active_request_id FROM sessions WHERE expired=0 AND (expires_at<=? OR absolute_expires_at<=?)',(now,now)).fetchall()
            for row in rows:
                db.execute('DELETE FROM turns WHERE session_id=?',(row['session_id'],))
                db.execute("UPDATE sessions SET expired=1,token_hash='',shown_media='[]',active_request_id=NULL,active_until=NULL WHERE session_id=?",(row['session_id'],))
            # Chat and reset keys are only needed during the session lifetime. Commercial retry keys remain with records.
            db.execute("DELETE FROM operations WHERE kind IN ('chat','cancel','reset') AND scope IN (SELECT session_id FROM sessions WHERE expired=1)")
            # No permanent tombstones for conversations without commercial data.
            db.execute("DELETE FROM sessions WHERE expired=1 AND NOT EXISTS (SELECT 1 FROM leads WHERE leads.session_id=sessions.session_id) AND NOT EXISTS (SELECT 1 FROM vouchers WHERE vouchers.session_id=sessions.session_id)")
            return [dict(row) for row in rows]

    def health(self):
        with closing(self.connect()) as db:
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            return ({'sessions','turns','leads','vouchers','operations','lead_tracking','lead_activity','lead_tasks'} <= tables
                    and db.execute('PRAGMA quick_check').fetchone()[0]=='ok' and not db.execute('PRAGMA foreign_key_check').fetchall())

    def backup(self, destination):
        return backup_sqlite(self.path, self.connect, destination)

    def list_operational(self,kind,limit=100,offset=0,status=None):
        if kind not in ('leads','vouchers'): raise ValueError('Invalid resource')
        with closing(self.connect()) as db:
            if kind=='leads':
                rows=db.execute('SELECT l.*,s.funnel_stage AS stage FROM leads l LEFT JOIN sessions s USING(session_id) ORDER BY l.created_at DESC,l.lead_id LIMIT ? OFFSET ?',(limit,offset))
            else:
                where=' WHERE v.status=?' if status else ''
                values=(status,limit,offset) if status else (limit,offset)
                rows=db.execute('SELECT v.*,l.name AS lead_name,r.review_note,r.reviewed_by,r.reviewed_at FROM vouchers v LEFT JOIN leads l USING(lead_id) LEFT JOIN voucher_reviews r USING(voucher_id)'+where+' ORDER BY v.created_at DESC,v.voucher_id LIMIT ? OFFSET ?',values)
            return [{k:row[k] for k in row.keys() if k!='file_reference'} for row in rows]

    def review_voucher(self,identifier,status,note,actor,request_id):
        from persistence.audit import append_audit
        if status not in ('approved','rejected') or len(note)>1000: raise ValueError('Invalid review')
        with self.transaction() as db:
            row=db.execute('SELECT * FROM vouchers WHERE voucher_id=?',(identifier,)).fetchone()
            if not row: raise RuntimeConflict('voucher_not_found',404)
            if row['status']!='pending_review': raise RuntimeConflict('voucher_review_final',409)
            now=self.clock()
            db.execute("UPDATE vouchers SET status=?,updated_at=? WHERE voucher_id=? AND status='pending_review'",(status,now,identifier))
            db.execute('INSERT INTO voucher_reviews VALUES(?,?,?,?)',(identifier,note,actor,now))
            result={'voucher_id':identifier,'status':status,'reviewed_by':actor,'reviewed_at':now,'review_note':note}
            if row['lead_id']:
                from persistence.lead_schema import activity
                activity(db,row['lead_id'],'voucher_'+status,actor,now,data={'voucher_id':identifier})
            append_audit(db,actor,'vouchers.review','vouchers',identifier,dict(row),result,request_id,now)
            return result

    def admin_audit(self,limit=100,offset=0,filters=None):
        from persistence.audit import decode_audit
        with closing(self.connect()) as db:
            from persistence.audit import audit_where
            where,values=audit_where(filters)
            return [decode_audit(r) for r in db.execute('SELECT * FROM admin_audit_log '+where+' ORDER BY timestamp DESC,id DESC LIMIT ? OFFSET ?',(*values,limit,offset))]

    def administrative_counts(self):
        with closing(self.connect()) as db:
            return {'leads':db.execute('SELECT count(*) FROM leads WHERE created_at>=?',(self.clock()-7*86400,)).fetchone()[0],
                    'vouchers':db.execute("SELECT count(*) FROM vouchers WHERE status='pending_review'").fetchone()[0]}
