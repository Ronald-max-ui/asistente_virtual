"""
services/intent_service.py — Detección de intención comercial/transaccional.

Se usa para escalar automáticamente la persona de Lía de "info" (Consulta)
a "sales" (Vendedora) cuando el usuario pregunta por costos, matrícula, etc.
"""
import re
import unicodedata

PERSONA_INFO  = "info"
PERSONA_SALES = "sales"
PERSONAS_VALIDAS = (PERSONA_INFO, PERSONA_SALES)

# Raíces/frases (ya normalizadas: minúsculas, sin tildes).
_PALABRAS_COMERCIALES = (
    "costo", "cuesta", "cuanto sale", "cuanto cobran", "precio", "tarifa",
    "pension", "mensualidad", "matricula", "matricular", "inscrib", "inscripcion",
    "requisito", "turno", "horario", "como postulo", "postular", "postulacion",
    "vacante", "admision", "cupos", "descuento", "beca", "pagar", "yape",
)

_RE_COMERCIAL = re.compile("|".join(re.escape(p) for p in _PALABRAS_COMERCIALES))


def _normalizar(texto: str) -> str:
    nfd = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def normalizar_persona(valor, default: str = PERSONA_SALES) -> str:
    """Devuelve 'info' o 'sales'; cualquier otro valor cae en `default`."""
    v = (valor or "").strip().lower()
    return v if v in PERSONAS_VALIDAS else default


def detectar_intencion_comercial(texto: str) -> bool:
    """True si el texto contiene señales de intención transaccional/comercial."""
    if not texto:
        return False
    return bool(_RE_COMERCIAL.search(_normalizar(texto)))
