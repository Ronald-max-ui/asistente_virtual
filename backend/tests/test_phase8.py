import asyncio,io,json,os,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import AsyncMock,patch
from dataclasses import replace
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_phase1_api import load_server
from test_phase3 import valid_png
from security.config import SecuritySettings
from runtime_config import PerformanceSettings
from production import validate_production
from services.llm_protocol import AssistantReply
from session_manager import SessionManager
from persistence.sqlite_runtime_repository import SQLiteRuntimeRepository

class ProductionTests(unittest.TestCase):
    def config(self):
        from knowledge_config import IndexSettings
        return types.SimpleNamespace(app_env='production',admin_api_token='a'*40,groq_api_key='gsk_real_private_example_removed'.replace('_example',''),
            commercial_db_path=Path(tempfile.gettempdir())/'commercial.sqlite3',
            sessions=types.SimpleNamespace(path=Path(tempfile.gettempdir())/'runtime.sqlite3'),
            knowledge_index=IndexSettings(Path(tempfile.gettempdir())/'index'))
    def test_production_origins_reject_http_local_and_wildcard(self):
        for origin in ['http://lia.example.org','https://localhost','https://127.0.0.1','https://[::1]','*']:
            with patch.dict(os.environ,APP_ENV='production',ALLOWED_ORIGINS=origin),self.assertRaises(ValueError):SecuritySettings.from_env()
        with patch.dict(os.environ,APP_ENV='production',ALLOWED_ORIGINS='https://lia.example.org'):
            self.assertEqual(SecuritySettings.from_env().allowed_origins,('https://lia.example.org',))
    def test_credentials_storage_and_invalid_index_rejected(self):
        with patch('services.knowledge_index.index_status',return_value={'status':'ready'}):
            cfg=self.config();validate_production(cfg)
            for field,value in [('admin_api_token',''),('admin_api_token','replace_'+'x'*40),('groq_api_key','test-key'),('groq_api_key','')]:
                cfg=self.config();setattr(cfg,field,value)
                with self.assertRaises(ValueError):validate_production(cfg)
            cfg=self.config();cfg.commercial_db_path=Path(__file__).resolve().parents[2]/'avatar-kiosk/public/leak.sqlite3'
            with self.assertRaises(ValueError):validate_production(cfg)
        with patch('services.knowledge_index.index_status',return_value={'status':'invalid'}),self.assertRaises(ValueError):validate_production(self.config())
    def test_production_prewarm_default_and_explicit_override(self):
        with patch.dict(os.environ,APP_ENV='production'):
            with patch.dict(os.environ,clear=False):
                os.environ.pop('KNOWLEDGE_PREWARM',None)
                self.assertTrue(PerformanceSettings.from_env().knowledge_prewarm)
            with patch.dict(os.environ,KNOWLEDGE_PREWARM='false'):self.assertFalse(PerformanceSettings.from_env().knowledge_prewarm)
    def test_invalid_environment_is_rejected(self):
        from runtime_config import environment
        with patch.dict(os.environ,APP_ENV='prod'),self.assertRaises(ValueError):environment()

    def test_retention_is_configuration_only(self):
        from retention_policy import RetentionPolicy
        with patch.dict(os.environ,RETENTION_LEADS_DAYS='365'):
            self.assertEqual(RetentionPolicy.from_env().leads_days,365)
        with patch.dict(os.environ,RETENTION_VOUCHERS_DAYS='0'),self.assertRaises(ValueError):RetentionPolicy.from_env()

class OperationalTests(unittest.TestCase):
    def test_frontend_headers_match_proxy_and_private_cache_remains(self):
        from security.frontend import FrontendHeaders,FRONTEND_CSP
        from fastapi.staticfiles import StaticFiles
        server=load_server()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'assets').mkdir();(root/'index.html').write_text('<html></html>')
            (root/'assets/index-abcdef12.js').write_text('/* fixture */')
            server.app.mount('/',StaticFiles(directory=root,html=True))
            server.app.add_middleware(FrontendHeaders)
            with TestClient(server.app) as client:
                html=client.get('/');asset=client.get('/assets/index-abcdef12.js')
                self.assertEqual(html.headers['cache-control'],'no-cache')
                self.assertEqual(html.headers['content-security-policy'],FRONTEND_CSP)
                self.assertNotIn('unsafe-eval',FRONTEND_CSP)
                self.assertIn('immutable',asset.headers['cache-control'])
                self.assertEqual(client.get('/api/config').headers['cache-control'],'no-cache')
                self.assertEqual(client.get('/api/admin/settings').headers['cache-control'],'no-store')
                self.assertEqual(html.headers['x-content-type-options'],'nosniff')
                self.assertIn(FRONTEND_CSP,(Path(__file__).resolve().parents[2]/'deploy/nginx.conf.example').read_text())

    def test_prewarm_keeps_liveness_available_and_readiness_waits(self):
        server=load_server();svc=server.app.state.services
        svc.conversation.performance=replace(svc.conversation.performance,knowledge_prewarm=True)
        async def slow():await asyncio.sleep(2)
        svc.knowledge.warmup_call=slow
        with TestClient(server.app) as client:
            self.assertEqual(client.get('/health/live').status_code,200)
            with patch.object(svc,'health',return_value={'status':'ready','checks':{'knowledge':True}}):
                result=client.get('/health/ready');self.assertEqual(result.status_code,503)
                self.assertEqual(result.json()['prewarm']['status'],'warming')
    def test_prewarm_failure_is_sanitized_and_invalid_knowledge_not_ready(self):
        server=load_server();svc=server.app.state.services
        svc.conversation.performance=replace(svc.conversation.performance,knowledge_prewarm=True)
        svc.knowledge.warmup_call=AsyncMock(side_effect=ValueError('secret-private-path'))
        with TestClient(server.app) as client:
            with patch.object(svc,'health',return_value={'status':'ready','checks':{'knowledge':True}}):
                result=client.get('/health/ready');self.assertEqual(result.status_code,503)
                self.assertNotIn('secret-private-path',result.text)
                self.assertEqual(result.json()['knowledge']['status'],'invalid')
    def test_e2e_lead_payment_voucher_restart_reset(self):
        server=load_server(real_session_auth=True);svc=server.app.state.services
        with TestClient(server.app) as client:
            identity=client.post('/api/session',json={}).json();sid=identity['session_id']
            headers={'X-Session-Token':identity['session_token']}
            question={'mensaje':'Quiero pagar la inscripción de Turismo','session_id':sid,'persona':'sales','mode':'web'}
            reply=AssistantReply(assistant_text='Consulta de inscripción.',structured_actions=[{'type':'show_payment','program':'turismo','concept':'inscripcion'}],native_actions_present=True)
            with patch.object(server,'generar_respuesta_llm',AsyncMock(return_value=reply)),patch.object(server,'generar_audio_bytes',AsyncMock(return_value=b'audio')):
                response=client.post('/chat',json=question,headers=headers)
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['actions'][0]['amount'],'80')
            lead=client.post('/api/leads',data={'session_id':sid,'nombre':'Synthetic','whatsapp':'999888777','carrera':'turismo'},headers={**headers,'Idempotency-Key':'e2e-lead'}).json()
            voucher=client.post('/api/vouchers',data={'session_id':sid,'carrera':'turismo','concepto':'inscripcion','monto':'80'},
                headers={**headers,'Idempotency-Key':'e2e-voucher'},files={'imagen':('fixture.png',valid_png(),'image/png')})
            self.assertEqual(voucher.status_code,200,voucher.text)
            repository=svc.session.repository
            server.session_manager=SessionManager(repository=SQLiteRuntimeRepository(repository.path))
            self.assertEqual(client.post('/api/session',json={'session_id':sid},headers=headers).status_code,200)
            self.assertEqual(client.post('/reset-session',json={'mensaje':'','session_id':sid},headers=headers).status_code,200)
            self.assertEqual(svc.session.repository.snapshot(sid)['lead_id'],lead['lead_id'])
            saved=svc.session.repository.get_record('vouchers',voucher.json()['voucher_id'])
            self.assertEqual(saved['lead_id'],lead['lead_id']);self.assertEqual(saved['status'],'pending_review')
            self.assertEqual(svc.session.repository.snapshot(sid)['history'],[])
            self.assertEqual(client.get('/api/config').headers['cache-control'],'no-cache')
    def test_tts_failed_preserves_text_done_and_llm_failed_has_no_actions(self):
        server=load_server(real_session_auth=True)
        async def chunks():
            yield types.SimpleNamespace(choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content='Texto disponible. Otra oración.',tool_calls=None))])
        with TestClient(server.app) as client:
            identity=client.post('/api/session',json={}).json();headers={'X-Session-Token':identity['session_token']}
            body={'mensaje':'Información de Turismo','session_id':identity['session_id']}
            with patch.object(server,'stream_respuesta_llm',AsyncMock(return_value=chunks())),patch.object(server,'generar_audio_bytes',AsyncMock(side_effect=TimeoutError())):
                response=client.post('/chat/stream',json=body,headers=headers)
            events=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
            self.assertEqual(events[-1]['type'],'done');self.assertIn('Otra oración',events[-1]['full_text'])
            self.assertFalse(any(e['type']=='audio' for e in events))
            with patch.object(server,'stream_respuesta_llm',AsyncMock(side_effect=TimeoutError('private secret'))):
                response=client.post('/chat/stream',json=body,headers=headers)
            self.assertNotIn('private secret',response.text);self.assertNotIn('ui_action',response.text)
            self.assertIn('"type": "error"',response.text)
if __name__=='__main__':unittest.main()
