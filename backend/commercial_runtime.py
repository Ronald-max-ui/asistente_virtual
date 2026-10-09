"""Configuración comercial independiente de Groq y del directorio de ejecución."""
from pathlib import Path
from threading import RLock
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / '.env')
_repository = None
_lock = RLock()

from runtime_config import private_path, administrative_token

def database_path(): return private_path('COMMERCIAL_DB_PATH', 'storage/commercial.sqlite3')

def admin_token(): return administrative_token()

def get_repository():
    global _repository
    with _lock:
        if _repository is None:
            from persistence.sqlite_repository import SQLiteRepository
            _repository = SQLiteRepository(database_path())
        return _repository
