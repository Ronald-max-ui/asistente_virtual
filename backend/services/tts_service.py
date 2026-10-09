"""
services/tts_service.py — Síntesis de voz con Edge-TTS completamente en memoria.

Mejora crítica: elimina el archivo respuesta.mp3 como estado global compartido.
El audio se genera y almacena en un BytesIO en RAM, nunca toca el disco.
Esto elimina la race condition del prototipo donde dos peticiones concurrentes
podían corromper o cruzar el audio de distintos usuarios.
"""
import io
import asyncio

import edge_tts

from config import settings
from security.config import SecuritySettings


async def generar_audio_bytes(texto: str, *, configuration=None, voice=None) -> bytes:
    """
    Sintetiza el texto con Edge-TTS y retorna los bytes de audio MP3 en memoria.

    Usa el método stream() (async generator) para construir el audio en un buffer
    BytesIO sin escribir nada al sistema de archivos.

    Args:
        texto: Texto a sintetizar.

    Returns:
        Bytes del audio MP3 generado.

    Raises:
        RuntimeError: Si Edge-TTS no devuelve datos de audio.
    """
    buffer = io.BytesIO()
    limits = getattr(configuration or settings, 'security', SecuritySettings())
    from domain.voice import VoiceConfig
    from types import SimpleNamespace
    selected=VoiceConfig.model_validate(voice) if voice is not None else SimpleNamespace(voice_id=(configuration or settings).tts_voice,rate=(configuration or settings).tts_rate,pitch='+0Hz',volume='+0%',enabled=True)
    if not selected.enabled:raise RuntimeError('Speech disabled')
    comunicador = edge_tts.Communicate(texto, selected.voice_id, rate=selected.rate, pitch=selected.pitch,volume=selected.volume,
        connect_timeout=10, receive_timeout=int(limits.tts_timeout))

    stream = comunicador.stream()
    try:
        async with asyncio.timeout(limits.tts_timeout):
            async for chunk in stream:
                if chunk["type"] == "audio":
                    if buffer.tell() + len(chunk['data']) > 5 * 1024 * 1024:
                        raise RuntimeError('Audio demasiado grande')
                    buffer.write(chunk["data"])
    finally:
        await stream.aclose()

    audio_bytes = buffer.getvalue()
    if not audio_bytes:
        raise RuntimeError(
            "Edge-TTS no generó audio"
        )

    return audio_bytes
