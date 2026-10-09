"""Único adaptador SQL: SQLite, montos decimales como TEXT, escrituras atómicas."""
import json
import sqlite3
from runtime_config import sqlite_timeout
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from persistence.repository import RepositoryConflict

_SCHEMA = """
CREATE TABLE IF NOT EXISTS programs(id TEXT PRIMARY KEY, name TEXT NOT NULL, enabled INTEGER NOT NULL, academic_path TEXT, data_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, created_by TEXT, updated_by TEXT);
CREATE TABLE IF NOT EXISTS program_aliases(program_id TEXT NOT NULL REFERENCES programs(id), alias TEXT UNIQUE NOT NULL, PRIMARY KEY(program_id,alias));
CREATE TABLE IF NOT EXISTS modalities(program_id TEXT NOT NULL REFERENCES programs(id), code TEXT NOT NULL, PRIMARY KEY(program_id,code));
CREATE TABLE IF NOT EXISTS shifts(program_id TEXT NOT NULL REFERENCES programs(id), code TEXT NOT NULL, PRIMARY KEY(program_id,code));
CREATE TABLE IF NOT EXISTS campaigns(id TEXT PRIMARY KEY, name TEXT NOT NULL, starts_on TEXT NOT NULL, ends_on TEXT NOT NULL, enabled INTEGER NOT NULL, data_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, created_by TEXT, updated_by TEXT);
CREATE TABLE IF NOT EXISTS prices(id TEXT PRIMARY KEY, program_id TEXT NOT NULL REFERENCES programs(id), modality TEXT, shift TEXT, concept TEXT NOT NULL, amount TEXT, currency TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('active','free','pending','inactive')), campaign_id TEXT REFERENCES campaigns(id), data_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, created_by TEXT, updated_by TEXT,
CHECK((status='pending' AND amount IS NULL) OR (status='free' AND amount IS NOT NULL AND CAST(amount AS NUMERIC)=0) OR (status='active' AND amount IS NOT NULL AND CAST(amount AS NUMERIC)>0) OR status='inactive'),
FOREIGN KEY(program_id,modality) REFERENCES modalities(program_id,code) DEFERRABLE INITIALLY DEFERRED,
FOREIGN KEY(program_id,shift) REFERENCES shifts(program_id,code) DEFERRABLE INITIALLY DEFERRED);
CREATE INDEX IF NOT EXISTS price_scope ON prices(program_id,concept,campaign_id);
CREATE TABLE IF NOT EXISTS promotions(id TEXT PRIMARY KEY, price_id TEXT NOT NULL REFERENCES prices(id), data_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, created_by TEXT, updated_by TEXT);
CREATE TABLE IF NOT EXISTS avatars(id TEXT PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL, enabled INTEGER NOT NULL, active INTEGER NOT NULL CHECK(active=0 OR enabled=1), data_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, created_by TEXT, updated_by TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS single_active_avatar ON avatars(active) WHERE active=1;
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, created_by TEXT, updated_by TEXT);
CREATE TABLE IF NOT EXISTS configuration_migrations(key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, applied_at TEXT NOT NULL);

"""
_SCHEMA += '''
CREATE TABLE IF NOT EXISTS branding_assets(id TEXT PRIMARY KEY,purpose TEXT NOT NULL,filename TEXT UNIQUE NOT NULL,mime TEXT NOT NULL,sha256 TEXT NOT NULL,width INTEGER NOT NULL,height INTEGER NOT NULL,created_at REAL NOT NULL,created_by TEXT NOT NULL);
'''
_TABLES = {'programs','prices','campaigns','avatars'}

def _now(): return datetime.now(timezone.utc).isoformat()

def _dump(value): return json.dumps(value,ensure_ascii=False,separators=(',',':'))

class SQLiteRepository:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True,exist_ok=True)
        db = self._connect()
        try:
            if db.execute('PRAGMA user_version').fetchone()[0] > 3:
                raise ValueError('Versión de base comercial no compatible')
            from persistence.admin_schema import SCHEMA as ADMIN_SCHEMA
            from security.admin_policy import ROLES
            db.executescript('BEGIN IMMEDIATE;\n' + _SCHEMA + ADMIN_SCHEMA)
            db.executemany('INSERT OR IGNORE INTO admin_roles(id) VALUES(?)', [(r,) for r in ROLES])
            db.execute('PRAGMA user_version=3')
            db.commit()
            db.execute('PRAGMA journal_mode=WAL')
        finally:
            db.close()
        if os.name != 'nt': os.chmod(self.path, 0o600)
    def _connect(self):
        timeout = sqlite_timeout()
        db = sqlite3.connect(self.path, timeout=timeout)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA synchronous=FULL')
        return db

    def health(self):
        if not self.path.is_file(): return False
        db = self._connect()
        try:
            return db.execute('PRAGMA quick_check').fetchone()[0] == 'ok' and not db.execute('PRAGMA foreign_key_check').fetchone()
        finally: db.close()

    def backup(self, destination):
        from persistence.sqlite_backup import backup_sqlite
        return backup_sqlite(self.path, self._connect, destination)
    @contextmanager
    def transaction(self, *, write=False):
        db = self._connect()
        try:
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield SQLiteUnit(db)
            db.commit()
        except sqlite3.IntegrityError as exc:
            db.rollback()
            raise RepositoryConflict('Identificador/alias duplicado, variante o referencia inexistente, o estado incompatible') from exc
        except Exception:
            db.rollback()
            raise
        finally: db.close()

class SQLiteUnit:
    def __init__(self, db): self.db=db
    def _table(self,resource):
        if resource not in _TABLES: raise ValueError('Recurso no permitido')
        return resource
    def _decode(self,row):
        result=json.loads(row['data_json'])
        result.update({key:row[key] for key in ('created_at','updated_at','created_by','updated_by')})
        # Las columnas normalizadas son autoritativas; JSON conserva campos extensibles.
        for key in ('name','academic_path','modality','shift','concept','amount','currency','status','campaign_id','starts_on','ends_on','url'):
            if key in row.keys(): result[key]=row[key]
        for key in ('active','enabled'):
            if key in row.keys(): result[key]=bool(row[key])
        if 'program_id' in row.keys():
            result['program']=row['program_id']
            result['promotions']=[json.loads(p['data_json']) for p in self.db.execute(
                'SELECT data_json FROM promotions WHERE price_id=? ORDER BY id',(row['id'],))]
        return result
    def list(self,resource):
        table=self._table(resource)
        return [self._decode(row) for row in self.db.execute(f'SELECT * FROM {table} ORDER BY id')]
    def get(self,resource,identifier):
        table=self._table(resource)
        row=self.db.execute(f'SELECT * FROM {table} WHERE id=?',(identifier,)).fetchone()
        return self._decode(row) if row else None
    def save(self,resource,identifier,data,actor):
        table=self._table(resource)
        old=self.get(resource,identifier)
        now=_now()
        columns={'id':identifier,'data_json':_dump(data),'created_at':old['created_at'] if old else now,'updated_at':now,'created_by':old['created_by'] if old else actor,'updated_by':actor}
        if table=='programs': columns.update(name=data['name'],enabled=int(data['enabled']),academic_path=data['academic_path'])
        if table=='campaigns': columns.update(name=data['name'],starts_on=data['starts_on'],ends_on=data['ends_on'],enabled=int(data['enabled']))
        if table=='prices': columns.update(program_id=data['program'],modality=data['modality'],shift=data['shift'],concept=data['concept'],amount=data['amount'],currency=data['currency'],status=data['status'],campaign_id=data['campaign_id'])
        if table=='avatars':
            if data['active']:
                # Cambiar la selección previa dentro de esta misma transacción.
                for avatar in self.list('avatars'):
                    if avatar['active'] and avatar['id']!=identifier:
                        self.db.execute('UPDATE avatars SET active=0,updated_at=?,updated_by=? WHERE id=?',(now,actor,avatar['id']))
            columns.update(name=data['name'],url=data['url'],enabled=int(data['enabled']),active=int(data['active']))
        fields=list(columns)
        updates=','.join(f'{key}=excluded.{key}' for key in fields if key not in ('id','created_at','created_by'))
        self.db.execute(f"INSERT INTO {table} ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)}) ON CONFLICT(id) DO UPDATE SET {updates}",list(columns.values()))
        if table=='programs':
            from services.consent_service import normalizar
            for child in ('program_aliases','modalities','shifts'):
                self.db.execute(f'DELETE FROM {child} WHERE program_id=?',(identifier,))
            for alias in set(normalizar(n) for n in [identifier,identifier.replace('_',' '),data['name'],*data['aliases']]):
                self.db.execute('INSERT INTO program_aliases(program_id,alias) VALUES (?,?)',(identifier,alias))
            for name,values in [('modalities',data['modalities']),('shifts',data['shifts'])]:
                for value in values: self.db.execute(f'INSERT INTO {name}(program_id,code) VALUES (?,?)',(identifier,value))
        if table=='prices':
            existing={row['id'] for row in self.db.execute('SELECT id FROM promotions WHERE price_id=?',(identifier,))}
            desired=set()
            for promo in data['promotions']:
                promo_id=identifier+':'+promo['id']
                desired.add(promo_id)
                self.db.execute('INSERT INTO promotions VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET data_json=excluded.data_json,updated_at=excluded.updated_at,updated_by=excluded.updated_by',
                                (promo_id,identifier,_dump(promo),now,now,actor,actor))
            for stale in existing-desired:
                self.db.execute('DELETE FROM promotions WHERE id=?',(stale,))
        return self.get(resource,identifier)
    def settings(self):
        return {row['key']:json.loads(row['value_json']) for row in self.db.execute('SELECT key,value_json FROM settings')}
    def save_settings(self,data,actor):
        now=_now()
        for key,value in data.items():
            self.db.execute('INSERT INTO settings VALUES (?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at,updated_by=excluded.updated_by',(key,_dump(value),now,now,actor,actor))
    def migration_applied(self,key):
        return self.db.execute('SELECT 1 FROM configuration_migrations WHERE key=?',(key,)).fetchone() is not None
    def record_migration(self,key,fingerprint):
        self.db.execute('INSERT INTO configuration_migrations VALUES (?,?,?)',(key,fingerprint,_now()))

    def audit(self,actor,action,resource,identifier,before,after,request_id):
        from persistence.audit import append_audit
        return append_audit(self.db,actor,action,resource,identifier,before,after,request_id)

    def branding_asset(self,filename):
        row=self.db.execute('SELECT purpose FROM branding_assets WHERE filename=?',(filename,)).fetchone()
        return dict(row) if row else None
