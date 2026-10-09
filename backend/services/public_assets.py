"""Deterministic asset revisions, no external URLs or sensitive paths."""
import hashlib,re
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
def asset_url(url,branding_root=None):
    if not url or not re.fullmatch(r'/static/(?:avatars|media|branding)/[a-zA-Z0-9_-]+\.(?:vrm|png|webp|jpe?g)',url):return None
    path=(Path(branding_root)/url.rsplit('/',1)[1]) if url.startswith('/static/branding/') and branding_root else BASE/url.lstrip('/')
    version=hashlib.sha256(url.encode()).hexdigest()
    if path.is_file():
        stat=path.stat();version=hashlib.sha256(f'{url}:{stat.st_size}:{stat.st_mtime_ns}'.encode()).hexdigest()
    return url+'?v='+version
