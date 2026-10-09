"""Readiness local sin llamadas externas, secretos ni detalles de infraestructura."""
from pathlib import Path
from services.avatar_service import AvatarService
from services.pricing_service import PricingService
from services.commercial_service import validate_configuration
from security.logging import safe_event
from services.knowledge_index import index_status

def readiness(repository, runtime_repository=None):
    checks = dict(database=False, configuration=False, avatar=False, pricing=False)
    try:
        checks['database'] = repository.health()
        with repository.transaction() as unit:
            validate_configuration(unit)
            checks['configuration'] = bool(unit.list('programs')) and bool(unit.settings().get('assistant_name'))
        config = AvatarService(repository).public_config()
        avatar = config['avatar']
        if avatar:
            base = Path(__file__).resolve().parents[1]
            path = (base / avatar['url'].lstrip('/')).resolve()
            checks['avatar'] = path.is_relative_to(base / 'static/avatars') and path.is_file()
        pricing = PricingService(repository=repository)
        catalogs = pricing.catalogs()
        # Pending sigue siendo una configuración válida; readiness no exige todos los montos confirmados.
        for program in catalogs:
            pricing.resolve(program, 'inscripcion')
        checks['pricing'] = True
    except Exception as exc:
        safe_event('readiness_failed', error=exc)
    if runtime_repository is not None:
        try:
            checks['runtime'] = runtime_repository.health()
        except Exception as exc:
            checks['runtime'] = False
            safe_event('runtime_readiness_failed', error=exc)
    knowledge = index_status(verify_vectors=True)
    # Stale is visible for deployment checks, but the validated active index
    # keeps serving while a draft source/build is fixed. Invalid cannot serve.
    checks['knowledge'] = knowledge['status'] in ('ready','stale')
    ready = all(checks.values())
    return {'status':'ready' if ready else 'not_ready', 'checks':checks,
            'knowledge':knowledge,
            'providers':{'groq':'not_probed', 'tts':'not_probed'}}
