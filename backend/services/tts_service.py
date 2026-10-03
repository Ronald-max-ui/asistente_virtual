"""
services/tts_service.py — Síntesis de voz con Edge-TTS completamente en memoria.

Mejora crítica: elimina el archivo respuesta.mp3 como estado global compartido.
El audio se genera y almacena en un BytesIO en RAM, nunca toca el disco.
Esto elimina la race condition del prototipo donde dos peticiones concurrentes
podían corromper o cruzar el audio de distintos usuarios.
"""
import io

import edge_tts

from config import settings


async def generar_audio_bytes(texto: str) -> bytes:
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
    comunicador = edge_tts.Communicate(texto, settings.tts_voice, rate=settings.tts_rate)

    async for chunk in comunicador.stream():
        if chunk["type"] == "audio":
            buffer.write(chunk["data"])

    audio_bytes = buffer.getvalue()
    if not audio_bytes:
        raise RuntimeError(
            f"Edge-TTS no generó audio para el texto: '{texto[:60]}...'"
        )

    return audio_bytes
