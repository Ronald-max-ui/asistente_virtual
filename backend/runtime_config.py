"""Validated operational/commercial environment parsing, independent of SDKs."""
import os
import math
from pathlib import Path
from dataclasses import dataclass
BASE = Path(__file__).resolve().parent

def private_path(variable, default):
    configured = Path(os.getenv(variable, default))
    path = (configured if configured.is_absolute() else BASE/configured).resolve()
    if path.is_relative_to(BASE/'static'): raise ValueError(variable + ' debe usar almacenamiento privado')
    return path

def positive_int(variable, default):
    value = int(os.getenv(variable, str(default)))
    if value <= 0: raise ValueError(variable + ' debe ser positivo')
    return value

def sqlite_timeout():
    value = float(os.getenv('SQLITE_BUSY_TIMEOUT_SECONDS', '5'))
    if not math.isfinite(value) or not 0 < value <= 30:
        raise ValueError('SQLITE_BUSY_TIMEOUT_SECONDS fuera de rango')
    return value

def administrative_token():
    token = os.getenv('ADMIN_API_TOKEN', '')
    if len(token)>512 or (os.getenv('APP_ENV')=='production' and token and
                         (len(token)<32 or token.startswith('replace_'))):
        raise ValueError('Configurar una credencial administrativa privada robusta')
    return token

@dataclass(frozen=True)
class SessionSettings:
    path: Path
    ttl: int
    lifetime: int
    persisted_turns: int
    history_chars: int
    request_lease: int
    context_turns: int
    cleanup_interval: int
    @classmethod
    def from_env(cls):
        return cls(private_path('RUNTIME_DATABASE_PATH', 'storage/runtime.sqlite3'),
            positive_int('SESSION_TTL_SECONDS',1800), positive_int('SESSION_LIFETIME_SECONDS',86400),
            positive_int('SESSION_PERSISTED_TURNS',12), positive_int('SESSION_HISTORY_MAX_CHARS',24000),
            positive_int('SESSION_REQUEST_LEASE_SECONDS',120), positive_int('SESSION_MAX_HISTORY_TURNS',4),
            positive_int('SESSION_CLEANUP_INTERVAL',60))

@dataclass(frozen=True)
class PerformanceSettings:
    tts_concurrency: int = 2
    tts_pending: int = 2
    knowledge_prewarm: bool = False
    @classmethod
    def from_env(cls):
        flag=os.getenv('KNOWLEDGE_PREWARM','true' if os.getenv('APP_ENV')=='production' else 'false').lower()
        if flag not in ('true','false'):raise ValueError('KNOWLEDGE_PREWARM must be true/false')
        value=cls(positive_int('TTS_CONCURRENCY',2),positive_int('TTS_PENDING_SENTENCES',2),flag=='true')
        if value.tts_concurrency>4 or value.tts_pending>8:raise ValueError('TTS limits out of range')
        return value

def environment():
    value=os.getenv('APP_ENV','development')
    if value not in ('development','test','production'):raise ValueError('APP_ENV inválido')
    return value
