"""Escritura privada en el mismo filesystem con publicación atómica."""
import os
import tempfile
from pathlib import Path

def atomic_private_write(path, content):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix='.upload-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
        if os.name != 'nt': os.chmod(path, 0o600)
    finally:
        Path(temporary).unlink(missing_ok=True)
