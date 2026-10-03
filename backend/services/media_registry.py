"""
services/media_registry.py — Catálogo de recursos multimedia del Instituto Tuinen Star.

Define los recursos visuales disponibles para el Modo Web.
Las rutas son relativas al directorio `backend/static/media/`.
Resuelve dinámicamente archivos existentes en disco (.webp, .jpg, .png, etc.).
"""
import os
from typing import Optional

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MEDIA_DIR = os.path.join(_BASE_DIR, "static", "media")
_EXTENSIONES_SOPORTADAS = (".webp", ".jpg", ".jpeg", ".png")

# ── Metadatos base del catálogo ───────────────────────────────────────────────
_CATALOGO_BASE: dict[str, dict] = {
    "gastronomia_uniforme": {
        "titulo": "Uniforme Oficial de Gastronomía",
        "descripcion": "Uniforme completo incluido en la matrícula: mandil, gorro y guantes.",
    },
    "gastronomia_talleres": {
        "titulo": "Talleres de Cocina - Gastronomía",
        "descripcion": "Estaciones de cocina equipadas para la práctica diaria.",
    },
    "turismo_salidas": {
        "titulo": "Salidas de Campo - Guía Oficial de Turismo",
        "descripcion": "Visitas arqueológicas y culturales en Cusco y alrededores.",
    },
    "bartender_barra": {
        "titulo": "Barra de Cócteles - Curso de Bartender",
        "descripcion": "Barra equipada con licores, cristalería y herramientas profesionales.",
    },
    "pasteleria_horno": {
        "titulo": "Hornos y Equipos - Panadería y Pastelería",
        "descripcion": "Hornos industriales, amasadoras y estaciones de trabajo.",
    },
    "instituto_fachada": {
        "titulo": "Instituto Tuinen Star - Sede San Sebastián",
        "descripcion": "Fachada principal de la sede en Calle Bellavista 130, San Sebastián.",
    },
    "yape_qr": {
        "titulo": "Pago con Yape",
        "descripcion": "Escanea el QR con tu app Yape para pagar tu matrícula. Número: 994 773 335.",
    },
}


def resolver_url_recurso(recurso_id: str) -> str:
    """
    Busca dinámicamente el archivo existente en `backend/static/media/`
    probando extensiones soportadas (.webp, .jpg, .jpeg, .png).
    Si no lo encuentra, devuelve un fallback con extensión .webp.
    """
    for ext in _EXTENSIONES_SOPORTADAS:
        filename = f"{recurso_id}{ext}"
        if os.path.isfile(os.path.join(_MEDIA_DIR, filename)):
            return f"/static/media/{filename}"
    return f"/static/media/{recurso_id}.webp"


def obtener_recurso(recurso_id: str) -> Optional[dict]:
    """Retorna los metadatos de un recurso por su ID, resolviendo la URL dinámicamente."""
    info = _CATALOGO_BASE.get(recurso_id)
    if not info:
        return None
    return {
        "titulo": info["titulo"],
        "descripcion": info["descripcion"],
        "url": resolver_url_recurso(recurso_id),
    }


def listar_recursos() -> list[dict]:
    """Retorna todos los recursos del catálogo con su ID y URL resuelta dinámicamente."""
    return [
        {
            "id": k,
            "titulo": v["titulo"],
            "descripcion": v["descripcion"],
            "url": resolver_url_recurso(k),
        }
        for k, v in _CATALOGO_BASE.items()
    ]
