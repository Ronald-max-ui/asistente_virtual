"""Deployment guard; never prints values or credentials. No provider requests."""
import re
from pathlib import Path

def validate_production(configuration):
    if getattr(configuration, 'app_env', 'development') != 'production': return
    from runtime_config import BASE
    from services.knowledge_index import index_status
    token=getattr(configuration,'admin_api_token','')
    key=getattr(configuration,'groq_api_key','')
    def placeholder(value):
        return not value or bool(re.search(r'replace|placeholder|example|changeme|your[_-]|test[_-]|<|>',value,re.I))
    from security.admin_config import AdminSettings
    admin=getattr(configuration,'admin',None) or AdminSettings(secure=True,cookie_name='__Secure-lia_admin_session')
    if not admin.secure: raise ValueError('Production requires Secure admin cookies')
    if admin.legacy_enabled and (len(token)<32 or placeholder(token)): raise ValueError('Production requires a private administrative credential')
    if len(key)<20 or placeholder(key): raise ValueError('Production requires a configured provider credential')
    public_roots=(BASE/'static',BASE.parent/'avatar-kiosk/public',BASE.parent/'avatar-kiosk/dist')
    if not configuration.knowledge_index.local_files_only or not configuration.knowledge_index.cache_dir:
        raise ValueError('Production requires explicitly provisioned local embedding artifacts')
    paths=[Path(configuration.commercial_db_path),configuration.sessions.path,configuration.knowledge_index.root,BASE/'storage/vouchers']
    if configuration.knowledge_index.cache_dir:paths.append(Path(configuration.knowledge_index.cache_dir))
    for path in paths:
        if any(path.resolve().is_relative_to(root.resolve()) for root in public_roots):
            raise ValueError('Production storage must not be served publicly')
    if index_status(configuration.knowledge_index,verify_vectors=True)['status']!='ready':
        raise ValueError('Production requires a valid current knowledge index')
