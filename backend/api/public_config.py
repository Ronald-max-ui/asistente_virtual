"""Only public assistant configuration and the approved media catalogue."""
import hashlib
import json
from pathlib import Path
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from api.commercial import service
from services.avatar_service import AvatarService
from services.media_registry import listar_recursos
router = APIRouter()
@router.get('/api/config')
def public_config(request: Request):
    payload = AvatarService(service(request).repository).public_config()
    # Revision also changes when the selected file is replaced under the same name.
    revision = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()
    avatar = payload.get('avatar')
    if avatar:
        path = Path(__file__).resolve().parents[1] / avatar['url'].lstrip('/')
        if path.is_file():
            stat = path.stat()
            revision += f'{stat.st_size}:{stat.st_mtime_ns}'.encode()
    etag = '"' + hashlib.sha256(revision).hexdigest() + '"'
    headers = {'Cache-Control': 'no-cache', 'ETag': etag}
    if request.headers.get('if-none-match') == etag:
        return Response(status_code=304, headers=headers)
    return JSONResponse(payload, headers=headers)
@router.get('/api/media')
def listar_medios(): return {'recursos':listar_recursos()}
