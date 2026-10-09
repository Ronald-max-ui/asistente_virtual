"""Application factory, middleware, routers and lifecycle (phase 6)."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from security.static import PublicStaticFiles
from config import settings
from app_services import build_services
from security.http import install_security
from security.logging import safe_event
from api.chat import router as chat_router
from api.sessions import router as sessions_router
from api.leads import router as leads_router
from api.vouchers import router as vouchers_router
from api.health import router as health_router
from api.public_config import router as config_router
from api.commercial import admin_router
from api.admin_identity import router as identity_router
from api.admin_panel import router as panel_router
from api.personalization import router as personalization_router
from api.lead_operations import router as lead_operations_router

@asynccontextmanager
async def lifespan(app):
    import time
    app.state.prewarm_status = 'warming' if app.state.services.conversation.performance.knowledge_prewarm else 'disabled'
    async def prewarm():
        started=time.perf_counter()
        try:
            await app.state.services.warmup(app.state.security_settings.rag_timeout)
            app.state.prewarm_status='ready'
            safe_event('knowledge_prewarm_ready',duration_ms=(time.perf_counter()-started)*1000)
        except Exception as exc:
            app.state.prewarm_status='failed' if isinstance(exc,TimeoutError) else 'invalid'
            safe_event('knowledge_prewarm_failed',error=exc,duration_ms=(time.perf_counter()-started)*1000)
    warmup_task=asyncio.create_task(prewarm()) if app.state.prewarm_status=='warming' else None
    cleanup_task = asyncio.create_task(app.state.services.session.iniciar_limpieza_periodica())
    safe_event('startup')
    try:
        yield
    finally:
        if warmup_task:
            warmup_task.cancel()
            await asyncio.gather(warmup_task,return_exceptions=True)
        cleanup_task.cancel()
        try: await cleanup_task
        except asyncio.CancelledError: pass
        try:
            await app.state.services.close()
        except Exception as exc:
            safe_event('provider_close_failed', error=exc)
        safe_event('shutdown')

def create_app(services=None, configuration=None, security_configuration=None):
    configuration = configuration or settings
    production = getattr(configuration, 'app_env', 'development') == 'production'
    app = FastAPI(title='Asistente Virtual IA - Instituto Tuinen Star', version='4.0.0', lifespan=lifespan,
        docs_url=None if production else '/docs', redoc_url=None if production else '/redoc',
        openapi_url=None if production else '/openapi.json')
    install_security(app, security_configuration)
    app.state.services = services or build_services(configuration)
    for router in (chat_router, sessions_router, leads_router, vouchers_router, health_router, config_router, admin_router, identity_router, panel_router, personalization_router, lead_operations_router):
        app.include_router(router)
    app.mount('/static', PublicStaticFiles(directory=str(Path(__file__).resolve().parent/'static')), name='static')
    return app

app = create_app()
