"""Backup consistente local. Nunca restaura ni sobrescribe una base existente."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
from commercial_runtime import database_path, BASE
import sqlite3
from persistence.sqlite_backup import backup_sqlite
from security.logging import safe_event

def backup_commercial(source,destination):
    source=Path(source).resolve()
    def connect():
        db=sqlite3.connect(source.as_uri()+'?mode=ro',uri=True,timeout=5)
        db.execute('PRAGMA foreign_keys=ON')
        return db
    return backup_sqlite(source,connect,destination)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=database_path())
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not args.database.is_file(): parser.error('Base de origen no disponible')
    target = args.output or BASE / 'storage' / 'backups' / ('commercial_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%f') + '.sqlite3')
    try:
        result = backup_commercial(args.database,target)
    except Exception as exc:
        safe_event('backup_failed', error=exc)
        parser.error('No se pudo crear un backup íntegro; verificar origen, permisos y destino')
    safe_event('backup_result',status=200)
    print('Backup consistente creado:', result.name)

if __name__ == '__main__': main()
