"""Canonical fingerprints shared by operations and persistence adapters."""
import hashlib
import json

def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
