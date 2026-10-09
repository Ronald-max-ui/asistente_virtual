"""Shared online SQLite backup; never copies an open database file."""
import os
import sqlite3
import tempfile
from pathlib import Path


def backup_sqlite(source_path, connect, destination):
    """SQLite backup API incluye WAL y obtiene una instantánea consistente."""
    target = Path(destination).resolve()
    base=Path(__file__).resolve().parents[1]
    if any(target.is_relative_to(root.resolve()) for root in (base/'static',base.parent/'avatar-kiosk/public',base.parent/'avatar-kiosk/dist')):
        raise ValueError('El backup no debe almacenarse en archivos públicos')
    if target == source_path or target.exists(): raise ValueError('Destino de backup existente o igual al origen')
    if not source_path.is_file(): raise ValueError('Base de origen no disponible')
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.backup-', dir=target.parent)
    os.close(fd)
    source = connect()
    copy = sqlite3.connect(temp)
    try:
        source.backup(copy, pages=128, sleep=0.05)
        if copy.execute('PRAGMA quick_check').fetchone()[0] != 'ok' or copy.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Backup no íntegro')
        copy.close()
        # Publicar sin sobrescribir un backup que otro proceso haya creado.
        os.link(temp, target)
        if os.name != 'nt': os.chmod(target, 0o600)
    finally:
        source.close()
        copy.close()
        Path(temp).unlink(missing_ok=True)
    return target
