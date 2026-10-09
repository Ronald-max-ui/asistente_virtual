"""Límites explícitos; no secretos ni dependencias de proveedores."""
import os
import math
import ipaddress
from dataclasses import dataclass, field
from urllib.parse import urlsplit

MAX_MESSAGE = 2000
MAX_SESSION_ID = 128
MAX_NAME = 120
MAX_PHONE = 24
MAX_NOTES = 2000
MAX_COMMERCIAL = 120
MAX_FILENAME = 128
MAX_ACTIONS = 8
MAX_ASSISTANT_TEXT = 16000
MAX_TOOL_ARGUMENTS = 4096

@dataclass(frozen=True)
class RatePolicy:
    limit: int
    window: int = 60

@dataclass(frozen=True)
class SecuritySettings:
    allowed_origins: tuple = ('http://localhost:5173', 'http://127.0.0.1:5173', 'http://localhost:8000', 'http://127.0.0.1:8000')
    json_max_bytes: int = 65536
    admin_max_bytes: int = 262144
    upload_max_bytes: int = 5 * 1024 * 1024
    upload_request_max_bytes: int = 6 * 1024 * 1024
    image_max_pixels: int = 12_000_000
    image_max_dimension: int = 6000
    body_timeout: float = 15
    groq_timeout: float = 25
    rag_timeout: float = 15
    tts_timeout: float = 20
    stream_timeout: float = 90
    provider_idle_timeout: float = 25
    max_active_ai: int = 8
    max_active_uploads: int = 4
    limiter_max_keys: int = 10000
    policies: dict = field(default_factory=lambda: {
        'chat': RatePolicy(30), 'leads': RatePolicy(5, 300), 'vouchers': RatePolicy(5, 300),
        'admin_login': RatePolicy(10), 'admin': RatePolicy(60), 'reset': RatePolicy(10), 'public': RatePolicy(120), 'static': RatePolicy(60),
    })

    @classmethod
    def from_env(cls):
        production = os.getenv('APP_ENV', 'development') == 'production'
        origins = tuple(o.strip() for o in os.getenv('ALLOWED_ORIGINS', '' if production else
                      'http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000').split(',') if o.strip())
        if not origins:
            raise ValueError('Configurar ALLOWED_ORIGINS explícitamente')
        for origin in origins:
            parsed = urlsplit(origin)
            if (parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or
                parsed.password or parsed.path or parsed.query or parsed.fragment or '*' in origin or
                (production and parsed.scheme != 'https')):
                raise ValueError('ALLOWED_ORIGINS requiere orígenes HTTP(S) exactos; HTTPS en producción')
            if production:
                host=(parsed.hostname or '').lower()
                try: local=ipaddress.ip_address(host).is_loopback
                except ValueError: local=host=='localhost' or host.endswith('.localhost')
                if local: raise ValueError('Origen local no permitido en producción')
        defaults = cls()
        fields = {
            'json_max_bytes': 'JSON_MAX_BYTES', 'admin_max_bytes': 'ADMIN_MAX_BYTES',
            'upload_max_bytes': 'UPLOAD_MAX_BYTES', 'upload_request_max_bytes': 'UPLOAD_REQUEST_MAX_BYTES',
            'image_max_pixels': 'IMAGE_MAX_PIXELS', 'image_max_dimension': 'IMAGE_MAX_DIMENSION',
            'max_active_ai': 'MAX_ACTIVE_AI_REQUESTS', 'max_active_uploads': 'MAX_ACTIVE_UPLOADS',
            'limiter_max_keys': 'RATE_LIMIT_MAX_KEYS',
        }
        values = {key: int(os.getenv(env, str(getattr(defaults, key)))) for key, env in fields.items()}
        for key, env in {'body_timeout':'REQUEST_BODY_TIMEOUT', 'groq_timeout':'GROQ_TIMEOUT',
                         'rag_timeout':'RAG_TIMEOUT', 'tts_timeout':'TTS_TIMEOUT', 'stream_timeout':'STREAM_TIMEOUT',
                         'provider_idle_timeout':'PROVIDER_IDLE_TIMEOUT'}.items():
            values[key] = float(os.getenv(env, str(getattr(defaults, key))))
        if any(not math.isfinite(value) or value <= 0 or value > 100_000_000 for value in values.values()):
            raise ValueError('Límite de seguridad fuera de rango')
        if values['upload_request_max_bytes'] <= values['upload_max_bytes']:
            raise ValueError('UPLOAD_REQUEST_MAX_BYTES debe admitir el overhead multipart')
        policies = {}
        for group, policy in defaults.policies.items():
            limit = int(os.getenv('RATE_' + group.upper() + '_LIMIT', str(policy.limit)))
            window = int(os.getenv('RATE_' + group.upper() + '_WINDOW', str(policy.window)))
            if not 1 <= limit <= 10000 or not 1 <= window <= 86400:
                raise ValueError('Política de rate limiting fuera de rango')
            policies[group] = RatePolicy(limit, window)
        return cls(allowed_origins=origins, policies=policies, **values)
