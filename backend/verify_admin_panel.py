"""Reproducible production guards and consistent backup checks; no production writes."""
import json,os,secrets,subprocess,sys,tempfile
from pathlib import Path
BASE=Path(__file__).resolve().parent

def main():
    from persistence.sqlite_repository import SQLiteRepository
    from persistence.sqlite_admin_repository import SQLiteAdminRepository
    from services.admin_service import AdminService
    from security.admin_config import AdminSettings
    from domain.admin import CreateUser
    from migrate_commercial import migrate,seed_configuration
    from backup_commercial import backup_commercial
    from verify_admin_backup import verify
    checks=[]
    with tempfile.TemporaryDirectory(prefix='lia-panel-verification-') as directory:
        root=Path(directory);repository=SQLiteRepository(root/'commercial.sqlite3');migrate(repository);seed_configuration(repository)
        service=AdminService(SQLiteAdminRepository(repository),AdminSettings(memory_cost=19456,time_cost=2,legacy_enabled=False))
        service.create(CreateUser(username='synthetic_backup_admin',display_name='Synthetic backup',password='Fixture!'+secrets.token_urlsafe(30),role='superadmin'),'verification','verification',first=True)
        target=backup_commercial(repository.path,root/'backup.sqlite3');checks.append({'case':'consistent_identity_commercial_backup','passed':verify(target)['status']=='valid'})
    env=dict(os.environ,APP_ENV='production',ALLOWED_ORIGINS='https://lia.example.org',GROQ_API_KEY=secrets.token_urlsafe(32),ADMIN_API_TOKEN='',ADMIN_LEGACY_TOKEN_ENABLED='false',ADMIN_COOKIE_SECURE='true',CHROMA_LOCAL_FILES_ONLY='true',CHROMA_MODEL_CACHE=str(BASE/'storage/embedding_models'),KNOWLEDGE_PREWARM='true')
    cases=[('session_mode_valid',{},0),('insecure_cookie',{'ADMIN_COOKIE_SECURE':'false'},1),('http_origin',{'ALLOWED_ORIGINS':'http://lia.example.org'},1),('localhost_origin',{'ALLOWED_ORIGINS':'https://localhost:5173'},1),('legacy_missing_token',{'ADMIN_LEGACY_TOKEN_ENABLED':'true'},1),('legacy_placeholder',{'ADMIN_LEGACY_TOKEN_ENABLED':'true','ADMIN_API_TOKEN':'replace_with_private_credential_placeholder'},1),('weak_argon',{'ADMIN_ARGON2_MEMORY_KIB':'1000'},1),('eternal_session',{'ADMIN_SESSION_LIFETIME_SECONDS':'999999999'},1)]
    for name,changes,expected in cases:
        result=subprocess.run([sys.executable,'-B',str(BASE/'validate_production.py')],env={**env,**changes},capture_output=True,timeout=60)
        checks.append({'case':name,'passed':result.returncode==expected})
    report={'passed':all(c['passed'] for c in checks),'checks':checks}
    print(json.dumps(report));return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
