"""Opaque optimistic revision; checked within the repository write transaction."""
import hashlib,json
from domain.errors import DomainError

def revision(record):
    return '"'+hashlib.sha256(json.dumps(record,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()+'"'

def check_revision(record,expected):
    if expected is not None and expected != revision(record):
        raise DomainError('admin_record_changed',409)
