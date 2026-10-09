"""Read-only verification of commercial identity/audit backup; never restore."""
import argparse,json,sqlite3
from contextlib import closing
from pathlib import Path
from security.admin_policy import ROLES

def verify(path):
    path=Path(path).resolve()
    if not path.is_file(): raise ValueError('Backup unavailable')
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required={'admin_users','admin_roles','admin_sessions','admin_audit_log','prices','campaigns','programs','avatars','settings'}
        if not required<=tables or db.execute('PRAGMA quick_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchone(): raise ValueError('Invalid administrative backup')
        for role,hashed in db.execute('SELECT role_id,password_hash FROM admin_users'):
            if role not in ROLES or not hashed.startswith('$argon2id$'): raise ValueError('Invalid identity record')
        return {'status':'valid','identity':True,'commercial_audit':True}
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--database',type=Path,required=True);args=parser.parse_args()
    try:result=verify(args.database)
    except Exception as exc: print(json.dumps({'status':'invalid','error_type':type(exc).__name__}));return 1
    print(json.dumps(result));return 0
if __name__=='__main__':raise SystemExit(main())
