"""Read-only verification of runtime snapshot, operational tables and vouchers."""
import argparse,hashlib,json,sqlite3,re
from pathlib import Path
from contextlib import closing

def verify(root):
 root=Path(root).resolve();manifest=json.loads((root/'manifest.json').read_text(encoding='utf8'));database=root/'runtime.sqlite3'
 digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
 if digest(database)!=manifest['runtime_sha256']:raise ValueError('Database hash mismatch')
 with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as db:
  if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('Database integrity failure')
  tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  if not {'leads','vouchers','lead_tracking','lead_activity','lead_tasks'}<=tables:raise ValueError('Operations tables missing')
  if db.execute('SELECT count(*) FROM leads l LEFT JOIN lead_tracking t USING(lead_id) WHERE t.lead_id IS NULL').fetchone()[0]:raise ValueError('Tracking incomplete')
  records={r[0] for r in db.execute('SELECT file_reference FROM vouchers')};counts={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('leads','lead_tracking','lead_activity','lead_tasks','vouchers')}
 if records!=set(manifest['vouchers']):raise ValueError('Voucher manifest incomplete')
 for filename,expected in manifest['vouchers'].items():
  path=(root/'vouchers'/filename).resolve()
  if not re.fullmatch(r'[a-f0-9]{32}\.(?:png|jpg|webp)',filename) or path.parent!=root/'vouchers' or digest(path)!=expected:raise ValueError('Voucher unavailable or inconsistent')
 return {'passed':True,'counts':counts,'integrity':'ok','read_only':True}
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('backup',type=Path);args=p.parse_args()
 try:print(json.dumps(verify(args.backup)))
 except (ValueError,OSError,sqlite3.Error):p.error('Backup inválido')
