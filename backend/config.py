"""
config.py — Configuración centralizada del Asistente Virtual.
Todas las constantes y variables de entorno viven aquí.
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # ── Groq LLM ────────────────────────────────────────────────────────────
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_model: str = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
    groq_max_tokens: int = int(os.getenv("GROQ_MAX_TOKENS", "180"))
    groq_temperature: float = float(os.getenv("GROQ_TEMPERATURE", "0.3"))

    # ── Edge-TTS ─────────────────────────────────────────────────────────────
    tts_voice: str = os.getenv("TTS_VOICE", "es-PE-CamilaNeural")
    tts_rate: str = os.getenv("TTS_RATE", "+10%")

    # ── ChromaDB / RAG ───────────────────────────────────────────────────────
    chroma_db_path: str = os.getenv("CHROMA_DB_PATH", "./chroma_db")
    chroma_collection_name: str = os.getenv("CHROMA_COLLECTION_NAME", "knowledge")
    chroma_embedding_model: str = os.getenv(
        "CHROMA_EMBEDDING_MODEL",
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    )
    chroma_k: int = int(os.getenv("CHROMA_K", "4"))

    # ── Sesiones ─────────────────────────────────────────────────────────────
    session_ttl_seconds: int = int(os.getenv("SESSION_TTL_SECONDS", "90"))
    session_max_history_turns: int = int(os.getenv("SESSION_MAX_HISTORY_TURNS", "4"))
    session_cleanup_interval_seconds: int = int(
        os.getenv("SESSION_CLEANUP_INTERVAL", "60")
    )

    # ── API ──────────────────────────────────────────────────────────────────
    cors_origins: list = os.getenv("CORS_ORIGINS", "*").split(",")
    host: str = os.getenv("HOST", "127.0.0.1")
    port: int = int(os.getenv("PORT", "8000"))


settings = Settings()

if not settings.groq_api_key:
    raise ValueError(
        "❌ No se encontró la variable GROQ_API_KEY en el archivo .env. "
        "El servidor no puede iniciarse."
    )
