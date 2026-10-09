"""Validate deployment without printing configuration values or secrets."""
import json

def main():
    try:
        from config import settings
        from production import validate_production
        if settings.app_env!='production':raise ValueError('Use APP_ENV=production')
        validate_production(settings)
        print(json.dumps({'status':'valid','prewarm_enabled':settings.performance.knowledge_prewarm}))
        return 0
    except Exception as exc:
        print(json.dumps({'status':'invalid','error_type':type(exc).__name__}))
        return 1
if __name__=='__main__':raise SystemExit(main())
