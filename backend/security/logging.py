"""Registro por eventos permitidos: nunca stringify de requests/excepciones."""
import logging
import re
from contextvars import ContextVar

request_id = ContextVar('request_id', default='startup')
logger = logging.getLogger('lia.security')

def configure_logging():
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        logger.addHandler(logging.StreamHandler())
    logger.propagate = False
    # SDKs pueden habilitar DEBUG desde entorno y registrar cuerpos/prompts.
    # Diagnóstico de proveedores exclusivamente mediante eventos permitidos.
    for name in ('groq', 'httpx', 'httpcore', 'edge_tts', 'aiohttp'):
        provider = logging.getLogger(name)
        provider.handlers = [logging.NullHandler()]
        provider.propagate = False
        provider.setLevel(logging.CRITICAL + 1)

def safe_event(event, *, error=None, **fields):
    safe = {'request_id': request_id.get(), 'event': re.sub(r'[^a-z0-9_]', '', event)[:64]}
    if error is not None:
        safe['error_type'] = type(error).__name__  # Nunca str(error), traceback ni proveedor.
    from services.performance import FIELDS
    for key in (*FIELDS,'status', 'group', 'duration_ms', 'bytes', 'record_id', 'count'):
        if key in fields:
            value = fields[key]
            if isinstance(value, (int, float)):
                safe[key] = value
            elif key in ('record_id', 'group') and isinstance(value, str):
                safe[key] = re.sub(r'[^a-zA-Z0-9_-]', '', value)[:64]
    logger.info('%s', safe)
