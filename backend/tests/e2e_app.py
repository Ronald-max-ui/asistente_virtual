"""Only for isolated browser E2E; never use this app in production."""
import asyncio,atexit,io,json,os,sys,tempfile,types,wave
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_phase1_api import load_server
from persistence.sqlite_repository import SQLiteRepository
from services.pricing_service import PricingService
from migrate_commercial import migrate,seed_configuration
from dataclasses import replace
from security.config import SecuritySettings,RatePolicy
from services.llm_protocol import AssistantReply
from services.commercial_service import CommercialService
folder=tempfile.TemporaryDirectory(prefix='lia-e2e-');atexit.register(folder.cleanup)
repository=SQLiteRepository(Path(folder.name)/'commercial.sqlite3');report=migrate(repository)
if report['rejected']:raise RuntimeError('Invalid fixture')
seed_configuration(repository)
commercial=CommercialService(repository)
if os.getenv('E2E_REAL_AVATAR')!='true': commercial.save('avatars',{'id':'fixture_missing','name':'Fallback fixture','url':'/static/avatars/fixture_missing.vrm','active':True,'enabled':True})
settings=commercial.settings();settings['kiosk_text_enabled']=True
# Strip repository audit fields before strict public settings validation.
from services.commercial_service import payload
commercial.save_settings(payload(settings))
security=SecuritySettings.from_env()
security=replace(security,policies={key:RatePolicy(10000) for key in security.policies})
fixture=load_server(security,real_session_auth=True,pricing=PricingService(repository=repository))
fixture.app.state.commercial_service=commercial
from services.admin_service import AdminService
from persistence.sqlite_admin_repository import SQLiteAdminRepository
fixture.app.state.admin_service=AdminService(SQLiteAdminRepository(repository))
fixture._VOUCHERS_DIR=Path(folder.name)/'vouchers';fixture._VOUCHERS_DIR.mkdir()
async def answer(history,rag,question,**kwargs):
    if 'fallo proveedor' in question.lower():raise TimeoutError('private fixture diagnostic')
    action=[]
    if 'datos' in question.lower(): action=[{'type':'show_contact','program':'turismo'}]
    elif 'pagar' in question.lower():action=[{'type':'show_payment','program':'turismo','concept':'inscripcion'}]
    return AssistantReply(assistant_text='Respuesta sin audio.' if 'sin audio' in question.lower() else 'Información académica de Turismo.',structured_actions=action,native_actions_present=True)
async def stream(history,rag,question,**kwargs):
    async def generate():
        reply=await answer(history,rag,question,**kwargs)
        yield types.SimpleNamespace(choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content=reply.assistant_text+' ',tool_calls=None))])
        if 'cancelar' in question.lower():await asyncio.sleep(10)
        if reply.structured_actions:
            action=reply.structured_actions[0];args={k:v for k,v in action.items() if k!='type'}
            call=types.SimpleNamespace(index=0,function=types.SimpleNamespace(name=action['type'],arguments=json.dumps(args)))
            yield types.SimpleNamespace(choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content='',tool_calls=[call]))])
    return generate()
observed_voice={}
async def speech(text,voice=None):
    if voice:observed_voice.update(voice)
    if 'sin audio' in text:raise TimeoutError()
    await asyncio.sleep(.15)
    buffer=io.BytesIO()
    with wave.open(buffer,'wb') as output:
        output.setnchannels(1);output.setsampwidth(2);output.setframerate(16000);output.writeframes(b'\x00\x00'*2400)
    return buffer.getvalue()
from services.providers import ConfiguredEdgeSpeechProvider
from services.voice_service import VoiceService
provider=ConfiguredEdgeSpeechProvider(speech,VoiceService(repository))
fixture.app.state.services.speech=provider;fixture.app.state.services.conversation.speech=provider
fixture.generar_respuesta_llm=answer;fixture.stream_respuesta_llm=stream;fixture.generar_audio_bytes=speech
app=fixture.app

# Fixture-only observation endpoint, registered before the public mount.
from fastapi import Depends
from security.auth import permission
@app.get('/api/admin/test/voice-observed')
def voice_observed(principal=Depends(permission('settings.read'))):return {'voice_id':observed_voice.get('voice_id')}

if os.getenv('E2E_DIST_PATH'):
    from fastapi.staticfiles import StaticFiles
    from security.frontend import FrontendHeaders
    app.mount('/',StaticFiles(directory=os.environ['E2E_DIST_PATH'],html=True))
    app.add_middleware(FrontendHeaders)
app.state.admin_api_token=os.getenv('E2E_ADMIN_API_TOKEN','')

# Simulate upload latency while preserving the real image/catalog/repository path.
original_submit=app.state.services.vouchers.submit
async def delayed_submit(*args,**kwargs):
    await asyncio.sleep(.5)
    return await original_submit(*args,**kwargs)
app.state.services.vouchers.submit=delayed_submit
