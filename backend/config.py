"""
config.py — Configuración centralizada del Asistente Virtual.
Todas las constantes y variables de entorno viven aquí.
"""
import os
from knowledge_config import IndexSettings
from runtime_config import SessionSettings, PerformanceSettings, BASE, positive_int, environment
from commercial_runtime import database_path, admin_token
from security.config import SecuritySettings
from security.logging import configure_logging
from dotenv import load_dotenv

load_dotenv(BASE / ".env")
configure_logging()


from retention_policy import RetentionPolicy

from security.admin_config import AdminSettings

class Settings:
    admin = AdminSettings.from_env()
    retention = RetentionPolicy.from_env()
    security = SecuritySettings.from_env()
    performance = PerformanceSettings.from_env()
    # Configuración comercial. Administración bloqueada cuando el token está vacío.
    commercial_db_path = str(database_path())
    admin_api_token = admin_token()
    # ── Groq LLM ────────────────────────────────────────────────────────────
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_model: str = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
    groq_max_tokens: int = positive_int("GROQ_MAX_TOKENS", 180)
    groq_temperature: float = float(os.getenv("GROQ_TEMPERATURE", "0.3"))

    # ── Edge-TTS ─────────────────────────────────────────────────────────────
    tts_voice: str = os.getenv("TTS_VOICE", "es-PE-CamilaNeural")
    tts_rate: str = os.getenv("TTS_RATE", "+10%")

    # ── ChromaDB / RAG ───────────────────────────────────────────────────────
    knowledge_index = IndexSettings.from_env()
    chroma_db_path: str = str(knowledge_index.root)
    chroma_collection_name: str = knowledge_index.collection
    chroma_embedding_model: str = knowledge_index.model
    chroma_k: int = knowledge_index.top_k

    # ── Sesiones ─────────────────────────────────────────────────────────────
    sessions = SessionSettings.from_env()
    session_ttl_seconds = sessions.ttl
    session_max_history_turns = sessions.context_turns
    session_cleanup_interval_seconds = sessions.cleanup_interval
    app_env = environment()

    # ── API ──────────────────────────────────────────────────────────────────
    cors_origins: list = list(security.allowed_origins)
    host: str = os.getenv("HOST", "127.0.0.1")
    port: int = positive_int("PORT", 8000)


settings = Settings()

if not settings.groq_api_key:
    raise ValueError(
        "❌ No se encontró la variable GROQ_API_KEY en el archivo .env. "
        "El servidor no puede iniciarse."
    )

from production import validate_production
validate_production(settings)
