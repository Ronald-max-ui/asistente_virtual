"""Consistent runtime snapshot and its immutable voucher images; never restore."""
import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from persistence.sqlite_backup import backup_sqlite
from session_manager import runtime_path
from security.storage import atomic_private_write
from security.logging import safe_event


def backup_runtime(repository, vouchers, destination):
    root, target = Path(vouchers).resolve(), Path(destination).resolve()
    public = Path(__file__).resolve().parent / 'static'
    if target.is_relative_to(public.resolve()) or target.is_relative_to(root) or target.exists():
        raise ValueError('Backup destination must be new and private')
    target.mkdir(parents=True, mode=0o700)
    try:
        db_path = repository.backup(target / 'runtime.sqlite3')
        with closing(sqlite3.connect(db_path)) as db:
            references = [r[0] for r in db.execute('SELECT file_reference FROM vouchers')]
        images = target / 'vouchers'
        images.mkdir(mode=0o700)
        files = {}
        for reference in references:
            source = (root / reference).resolve()
            if source.parent != root or source.suffix not in ('.png','.jpg','.webp') or not source.is_file():
                raise ValueError('Voucher reference unavailable')
            content = source.read_bytes()
            atomic_private_write(images / reference, content)
            files[reference] = hashlib.sha256(content).hexdigest()
        manifest = {'schema':1, 'created_at':datetime.now(timezone.utc).isoformat(),
            'runtime_sha256':file_hash(db_path), 'vouchers':files}
        atomic_private_write(target / 'manifest.json',json.dumps(manifest).encode())
        return target
    except BaseException:
        # Remove only files created in this new, verified output directory.
        for child in target.iterdir():
            if child.name == 'vouchers' and child.is_dir():
                for image in child.iterdir(): image.unlink()
                child.rmdir()
            elif child.is_file(): child.unlink()
        target.rmdir()
        raise


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda:source.read(65536), b''):
            digest.update(block)
    return digest.hexdigest()


class ReadOnlyRuntimeSnapshot:
    """CLI backups must not implicitly upgrade the source schema."""
    def __init__(self,path):self.path=Path(path).resolve()
    def backup(self,destination):
        def connect():
            db=sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True,timeout=5)
            db.execute('PRAGMA foreign_keys=ON')
            return db
        return backup_sqlite(self.path,connect,destination)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,default=runtime_path())
    parser.add_argument('--vouchers',type=Path,default=Path(__file__).resolve().parent/'storage/vouchers')
    parser.add_argument('--output',type=Path)
    args = parser.parse_args()
    if not args.database.is_file(): parser.error('Base operativa no disponible')
    target = args.output or args.database.parent/'backups'/('runtime_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%f'))
    try: result = backup_runtime(ReadOnlyRuntimeSnapshot(args.database), args.vouchers, target)
    except Exception as exc:
        safe_event('runtime_backup_failed',error=exc)
        parser.error('No se pudo crear un backup íntegro; verificar origen, archivos y permisos')
    safe_event('runtime_backup_result',status=200)
    print('Backup operativo consistente creado:',result.name)


if __name__ == '__main__': main()
