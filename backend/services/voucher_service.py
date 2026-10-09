"""Validación y normalización de imágenes; persistencia pertenece a operaciones."""
import asyncio
import io
import re
import warnings
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError
from fastapi import HTTPException
from security.config import MAX_FILENAME

Image.MAX_IMAGE_PIXELS = 12_000_000
FORMATS = {'JPEG': ('image/jpeg', '.jpg'), 'PNG': ('image/png', '.png'), 'WEBP': ('image/webp', '.webp')}

class LimitedBuffer(io.BytesIO):
    def __init__(self, limit):
        super().__init__()
        self.limit = limit
    def write(self, data):
        if self.tell() + len(data) > self.limit:
            raise HTTPException(413, 'Imagen normalizada demasiado grande')
        return super().write(data)

def validate_image(content, filename, mime, config):
    if len(filename) > MAX_FILENAME or not re.fullmatch(r'[\w ()-]+\.(?:jpe?g|png|webp)', filename, re.I):
        raise HTTPException(400, 'Nombre de archivo inválido')
    signature = ('PNG' if content.startswith(b'\x89PNG\r\n\x1a\n') else 'JPEG' if content.startswith(b'\xff\xd8\xff') else
                 'WEBP' if content[:4] == b'RIFF' and content[8:12] == b'WEBP' else None)
    if signature is None or mime != FORMATS[signature][0]:
        raise HTTPException(400, 'Formato de imagen inválido')
    suffix = Path(filename).suffix.lower()
    if suffix not in ({'.jpg','.jpeg'} if signature == 'JPEG' else {FORMATS[signature][1]}):
        raise HTTPException(400, 'La extensión no coincide con la imagen')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content), formats=list(FORMATS)) as image:
                width, height = image.size
                if (width < 1 or height < 1 or width > config.image_max_dimension or height > config.image_max_dimension
                        or width * height > config.image_max_pixels or getattr(image, 'n_frames', 1) != 1):
                    raise HTTPException(400, 'Dimensiones o animación no admitidas')
                if image.format != signature:
                    raise HTTPException(400, 'Formato de imagen inconsistente')
                image.verify()
            # verify valida estructura; load fuerza una decodificación completa y acotada.
            with Image.open(io.BytesIO(content), formats=[signature]) as image:
                image.load()
                oriented = ImageOps.exif_transpose(image)
                clean = oriented.convert('RGB' if signature == 'JPEG' else 'RGBA')
                clean.info.clear()
                output = LimitedBuffer(config.upload_max_bytes)
                clean.save(output, format=signature)
                normalized = output.getvalue()
                if len(normalized) > config.upload_max_bytes:
                    raise HTTPException(413, 'Imagen normalizada demasiado grande')
                return normalized, FORMATS[signature][1]
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise HTTPException(400, 'Imagen corrupta o no admitida') from exc

async def read_validated_image(upload, config):
    try:
        if upload.size is not None and upload.size > config.upload_max_bytes:
            raise HTTPException(413, 'Archivo demasiado grande')
        content = bytearray()
        while True:
            chunk = await upload.read(65536)
            if not chunk: break
            if len(content) + len(chunk) > config.upload_max_bytes:
                raise HTTPException(413, 'Archivo demasiado grande')
            content.extend(chunk)
        # Capacidad global de uploads acotada en middleware; ningún proceso externo/OCR.
        return await asyncio.to_thread(validate_image, bytes(content), upload.filename or '', upload.content_type, config)
    finally:
        await upload.close()
