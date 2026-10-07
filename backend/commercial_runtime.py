"""Configuración comercial independiente de Groq y del directorio de ejecución."""
import os
from pathlib import Path
from threading import RLock
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / '.env')
_repository = None
_lock = RLock()

def database_path():
    path = Path(os.getenv('COMMERCIAL_DB_PATH', 'storage/commercial.sqlite3'))
    return path.resolve() if path.is_absolute() else (BASE / path).resolve()

def admin_token():
    return os.getenv('ADMIN_API_TOKEN', '')

def get_repository():
    global _repository
    with _lock:
        if _repository is None:
            from persistence.sqlite_repository import SQLiteRepository
            _repository = SQLiteRepository(database_path())
        return _repository
