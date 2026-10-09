"""Consistent commercial database plus immutable approved branding assets."""
import argparse,hashlib,json,re,sqlite3
from pathlib import Path
from contextlib import closing
from datetime import datetime,timezone
from backup_commercial import backup_commercial
from commercial_runtime import database_path
from security.storage import atomic_private_write

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def backup_personalization(source,assets,destination):
    source,assets,target=map(lambda p:Path(p).resolve(),(source,assets,destination))
    public=Path(__file__).resolve().parent/'static'
    if target.exists() or target.is_relative_to(assets) or target.is_relative_to(public):raise ValueError('New private destination required')
    target.mkdir(parents=True,mode=0o700)
    try:
        snapshot=backup_commercial(source,target/'commercial.sqlite3')
        with closing(sqlite3.connect(snapshot)) as db:
            records=db.execute('SELECT filename,sha256 FROM branding_assets').fetchall()
        folder=target/'branding';folder.mkdir(mode=0o700);files={}
        for filename,expected in records:
            path=(assets/filename).resolve()
            if not re.fullmatch(r'[a-f0-9]{32}\.(?:png|jpg|webp)',filename) or path.parent!=assets or not path.is_file() or digest(path)!=expected:raise ValueError('Approved asset missing or inconsistent')
            atomic_private_write(folder/filename,path.read_bytes());files[filename]=expected
        manifest={'schema':1,'created_at':datetime.now(timezone.utc).isoformat(),'commercial_sha256':digest(snapshot),'branding':files}
        atomic_private_write(target/'manifest.json',json.dumps(manifest).encode());verify_backup(target);return target
    except BaseException:
        # Only the new, checked destination and files created by this operation.
        for file in (target/'branding').glob('*'):file.unlink()
        if (target/'branding').exists():(target/'branding').rmdir()
        for file in target.iterdir():file.unlink()
        target.rmdir();raise

def verify_backup(directory):
    root=Path(directory).resolve();manifest=json.loads((root/'manifest.json').read_text())
    if manifest.get('schema')!=1 or digest(root/'commercial.sqlite3')!=manifest['commercial_sha256']:raise ValueError('Database hash mismatch')
    with closing(sqlite3.connect((root/'commercial.sqlite3').as_uri()+'?mode=ro',uri=True)) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('Database integrity failure')
        rows=dict(db.execute('SELECT filename,sha256 FROM branding_assets'))
    if rows!=manifest['branding']:raise ValueError('Incomplete asset registry')
    for filename,expected in rows.items():
        path=(root/'branding'/filename).resolve()
        if path.parent!=root/'branding' or digest(path)!=expected:raise ValueError('Asset hash mismatch')
    return {'database':'ok','assets':len(rows),'integrity':'ok'}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--database',type=Path,default=database_path());parser.add_argument('--assets',type=Path);parser.add_argument('--output',type=Path);parser.add_argument('--check',type=Path);args=parser.parse_args()
    try:
        if args.check:print(json.dumps(verify_backup(args.check)));return
        if not args.output:parser.error('--output is required')
        backup_personalization(args.database,args.assets or args.database.parent/'branding',args.output);print('Backup de configuración y branding verificado.')
    except (ValueError,OSError,sqlite3.Error):parser.error('Backup inválido; revisar archivos, permisos e integridad')
if __name__=='__main__':main()
