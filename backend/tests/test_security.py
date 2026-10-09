"""Seguridad de Fase 2 con proveedores simulados y almacenamiento temporal."""
import asyncio
import io
import json
import logging
import tempfile
import types
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch
from PIL import Image
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_phase1_api import load_server, valid_png
from security.config import SecuritySettings, RatePolicy, MAX_ACTIONS
from security.rate_limit import MemoryRateLimitStore
from security.logging import safe_event
from security.providers import bounded_stream
from security.http import SecurityMiddleware
from services.voucher_service import validate_image
from services.llm_protocol import ToolCallCollector, AssistantReply
from services.action_service import ActionContext, procesar_acciones
from persistence.sqlite_repository import SQLiteRepository
from migrate_commercial import migrate, seed_configuration
from services.commercial_service import CommercialService, payload
from services.health_service import readiness

def image_bytes(format='PNG', size=(16,16)):
    buffer = io.BytesIO()
    Image.new('RGB', size, 'white').save(buffer, format=format)
    return buffer.getvalue()

class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.config = SecuritySettings()
        self.server = load_server(self.config)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.server._VOUCHERS_DIR = self.directory.name
        self.server._LEADS_DIR = self.directory.name
        self.client = TestClient(self.server.app, raise_server_exceptions=False)
        self.addCleanup(self.client.close)

    def voucher(self, content=None, filename='voucher.png', mime='image/png', amount='80', concept='inscripcion', **extra):
        return self.client.post('/api/vouchers', data={'monto':amount,'carrera':'Turismo','concepto':concept, **extra},
            files={'imagen':(filename, image_bytes() if content is None else content, mime)})

    def test_differentiated_rate_limits_and_health_exemption(self):
        policies = {k:RatePolicy(2) for k in self.config.policies}
        self.server.app.state.security_settings = replace(self.config, policies=policies)
        for path in ['/chat','/api/leads','/api/vouchers','/api/admin/programs','/reset-session']:
            for _ in range(2):
                self.assertNotEqual(self.client.post(path, json={}).status_code, 429)
            third = self.client.post(path, json={})
            self.assertEqual(third.status_code, 429, path)
            self.assertGreater(int(third.headers['retry-after']), 0)
        self.assertEqual(self.client.post('/chat/stream', json={'mensaje':''}).status_code, 429)
        for _ in range(5): self.assertEqual(self.client.get('/health').status_code, 200)

    def test_peer_address_cannot_be_replaced_with_forwarded_header(self):
        self.server.app.state.security_settings = replace(self.config, policies={**self.config.policies,'chat':RatePolicy(1)})
        self.assertEqual(self.client.post('/chat', json={'mensaje':''}, headers={'X-Forwarded-For':'1.1.1.1'}).status_code, 200)
        self.assertEqual(self.client.post('/chat', json={'mensaje':''}, headers={'X-Forwarded-For':'2.2.2.2'}).status_code, 429)

    def test_message_session_form_and_admin_fields_are_bounded(self):
        for body in [{'mensaje':'a'*2001}, {'mensaje':'ok','session_id':'a'*129}, {'mensaje':'ok','mode':'evil'},
                     {'mensaje':'ok','persona':'evil'}, {'mensaje':True}, {'mensaje':'ok','secret':'abc'}]:
            self.assertEqual(self.client.post('/chat', json=body).status_code, 422)
        response = self.client.post('/api/leads', data={'nombre':'a'*121,'whatsapp':'999888777','carrera':'turismo'})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn('a'*121, response.text)
        response = self.voucher(whatsapp='9'*25)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    def test_valid_lead_is_private_and_log_does_not_contain_phone(self):
        with self.assertLogs('lia.security',level='INFO') as logs:
            response = self.client.post('/api/leads',data={'nombre':'Persona de prueba','whatsapp':'+51 999 888 777',
                'carrera':'turismo','notas':'Información','session_id':'lead-security'})
        self.assertEqual(response.status_code,200)
        self.assertNotIn('999888777',' '.join(logs.output))
        lead = self.server.session_manager.repository.get_record('leads', response.json()['lead_id'])
        self.assertEqual(lead['whatsapp'], '+51999888777')
        self.assertEqual(list(Path(self.directory.name).glob('*.json')), [])
        self.assertEqual(self.client.post('/api/leads',data={'nombre':'Test','whatsapp':'-------','carrera':'turismo'}).status_code,422)

    def test_settings_cannot_store_credentials(self):
        self.server.app.state.admin_api_token = 'test-token'
        current = self.server.app.state.commercial_service.settings()
        response = self.client.put('/api/admin/settings',headers={'Authorization':'Bearer test-token'},
            json={**current,'voice':{'api_key':'a-private-key'}})
        self.assertEqual(response.status_code,422)
        self.assertNotIn('a-private-key',response.text)
        self.assertNotIn('a-private-key',self.client.get('/api/config').text)
        self.assertEqual(self.client.get('/api/admin/prices/'+'a'*129,
            headers={'Authorization':'Bearer test-token'}).status_code,422)

    def test_total_request_size_checks_content_length_and_chunked_body(self):
        self.server.app.state.security_settings = replace(self.config, json_max_bytes=512)
        response = self.client.post('/chat', content=b'x'*513, headers={'Content-Type':'application/json'})
        self.assertEqual(response.status_code, 413)
        response = self.client.post('/chat', content=iter([b'x'*300,b'x'*300]), headers={'Content-Type':'application/json'})
        self.assertEqual(response.status_code, 413)
        self.assertEqual(self.client.post('/chat', content=b'{}', headers={'Content-Encoding':'gzip'}).status_code, 400)

    def test_file_size_and_request_size_are_distinct(self):
        self.server.app.state.security_settings = replace(self.config, upload_max_bytes=64, upload_request_max_bytes=2048)
        self.assertEqual(self.voucher(content=b'x'*100).status_code, 413)
        self.assertEqual(self.voucher(content=b'x'*3000).status_code, 413)
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    def test_mime_extension_corruption_and_traversal_are_rejected(self):
        cases = [(image_bytes(),'photo.png','image/jpeg'), (image_bytes(),'photo.jpg','image/jpeg'),
                 (image_bytes(),'photo.jpg','image/png'), (b'\x89PNG\r\n\x1a\ncorrupt','photo.png','image/png'),
                 (image_bytes(),'../photo.png','image/png'), (image_bytes(),'..\\photo.png','image/png'),
                 (image_bytes(),'photo.png.exe','image/png'), (image_bytes(),'photo.exe.png','image/png'),
                 (image_bytes(),'a'*129+'.png','image/png')]
        for content, filename, mime in cases:
            # Nuevas IPs no son necesarias: límite alto exclusivo de este lote de validación.
            self.server.app.state.security_settings = replace(self.config, policies={**self.config.policies,'vouchers':RatePolicy(30)})
            self.assertEqual(self.voucher(content,filename,mime).status_code, 400, filename)
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    def test_dimensions_pixels_and_animation_are_rejected(self):
        config = replace(self.config, image_max_pixels=100, image_max_dimension=20)
        with self.assertRaises(HTTPException): validate_image(image_bytes(size=(11,11)), 'a.png','image/png',config)
        with self.assertRaises(HTTPException): validate_image(image_bytes(size=(21,1)), 'a.png','image/png',config)
        buffer = io.BytesIO()
        first = Image.new('RGB',(4,4),'white')
        first.save(buffer,format='PNG',save_all=True,append_images=[Image.new('RGB',(4,4),'black')])
        with self.assertRaises(HTTPException): validate_image(buffer.getvalue(),'a.png','image/png',self.config)

    def test_valid_formats_use_server_names_and_remove_trailing_content(self):
        for format, extension, mime in [('JPEG','.jpeg','image/jpeg'),('PNG','.png','image/png'),('WEBP','.webp','image/webp')]:
            response = self.voucher(image_bytes(format)+b'<script>secret</script>', 'nombre_cliente'+extension, mime)
            self.assertEqual(response.status_code, 200, response.text)
            identifier = response.json()['voucher_id']
            self.assertRegex(identifier, r'^[0-9a-f]{32}$')
            meta = self.server.session_manager.repository.get_record('vouchers', identifier)
            image = Path(self.directory.name)/meta['file_reference']
            self.assertNotIn('nombre_cliente', image.name)
            self.assertNotIn(b'<script>', image.read_bytes())
            self.assertEqual((meta['amount'],meta['program']), ('80','turismo'))
            with Image.open(image) as decoded: decoded.verify()

    def test_exif_orientation_is_applied_before_metadata_removal(self):
        buffer = io.BytesIO()
        image = Image.new('RGB',(2,3),'white')
        exif = image.getexif()
        exif[274] = 6
        image.save(buffer,format='JPEG',exif=exif)
        content, extension = validate_image(buffer.getvalue(),'camera.jpg','image/jpeg',self.config)
        with Image.open(io.BytesIO(content)) as decoded:
            self.assertEqual(decoded.size,(3,2))
            self.assertFalse(decoded.getexif())

    def test_cleanup_after_storage_failure(self):
        import services.operational_service as module
        with patch.object(module, 'atomic_private_write', side_effect=OSError('private-path secret-token')):
            response = self.voucher()
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('private-path', response.text)
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    def test_pricing_revalidates_after_decoding_and_blocks_free_pending(self):
        original = self.server.consultar_tarifa
        active = original('turismo','inscripcion')
        changed = {**active,'amount':'95'}
        with patch.object(self.server,'consultar_tarifa',side_effect=[active,changed]):
            self.assertEqual(self.voucher().status_code,409)
        for state, amount in [('free','0'),('pending',None)]:
            with patch.object(self.server,'consultar_tarifa',return_value={**active,'status':state,'amount':amount}):
                response = self.voucher()
                self.assertEqual(response.status_code,409)
                self.assertEqual(response.json()['code'],'price_free' if state=='free' else 'tariff_pending')
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    def test_admin_token_missing_wrong_and_never_exposed(self):
        self.server.app.state.admin_api_token = 'private-admin-token'
        for headers in [{}, {'Authorization':'Bearer wrong'}, {'Authorization':'Bearer '+'a'*513}]:
            response = self.client.get('/api/admin/settings',headers=headers)
            self.assertEqual(response.status_code,401)
            self.assertNotIn('private-admin-token', response.text)
            self.assertNotIn('Authorization', response.text)
        self.assertNotIn('private-admin-token', self.client.get('/api/config').text)
        self.server.app.state.admin_api_token = ''
        self.assertEqual(self.client.get('/api/admin/settings').status_code,503)

    def test_cors_headers_and_unsupported_origins(self):
        allowed = self.config.allowed_origins[0]
        response = self.client.options('/chat',headers={'Origin':allowed,'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'Content-Type'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers['access-control-allow-origin'],allowed)
        self.assertNotIn('access-control-allow-credentials',response.headers)
        for method in ['get','options']:
            response = getattr(self.client,method)('/api/config',headers={'Origin':'https://evil.example'})
            self.assertEqual(response.status_code,403)
            self.assertNotIn('access-control-allow-origin',response.headers)
        response = self.client.get('/api/config',headers={'Origin':allowed})
        self.assertEqual(response.headers['x-content-type-options'],'nosniff')
        self.assertIn("frame-ancestors 'none'",response.headers['content-security-policy'])
        self.assertEqual(response.headers['referrer-policy'],'no-referrer')
        self.assertRegex(response.headers['x-request-id'],r'^[0-9a-f]{32}$')
        denied = self.client.options('/chat',headers={'Origin':allowed,'Access-Control-Request-Method':'DELETE'})
        self.assertEqual(denied.status_code,400)
        self.assertEqual(denied.json()['code'],'cors_preflight_rejected')

    def test_errors_and_logs_do_not_expose_request_or_provider_secrets(self):
        private = '999888777 Authorization Bearer secret-token D:\\private\\db.sqlite3 SQL SELECT'
        with self.assertLogs('lia.security',level='INFO') as logs:
            safe_event('provider_failed',error=RuntimeError(private),phone='999888777',authorization='Bearer secret-token')
            with patch.object(self.server,'generar_respuesta_llm',AsyncMock(side_effect=RuntimeError(private))):
                response = self.client.post('/chat',json={'mensaje':'Hola','session_id':'security-error'})
        self.assertEqual(response.status_code,502)
        for value in ['999888777','secret-token','private\\db','SELECT','Traceback','Authorization']:
            self.assertNotIn(value,response.text)
            self.assertNotIn(value,' '.join(logs.output))
        self.assertEqual(self.client.get('/missing').status_code,404)
        self.assertNotIn('secret-token', self.client.post('/chat', json={'mensaje':{'password':'secret-token'}}).text)

    def test_provider_timeout_stream_error_cleanup_and_capacity_release(self):
        async def never(*args, **kwargs): await asyncio.sleep(10)
        self.server.app.state.security_settings = replace(self.config, groq_timeout=.01, provider_idle_timeout=.01)
        with patch.object(self.server,'generar_respuesta_llm',never):
            self.assertEqual(self.client.post('/chat',json={'mensaje':'Hola'}).status_code,503)
        self.assertEqual(self.server.app.state.active_requests.counts['chat'],0)

    def test_total_stream_deadline_and_active_capacity(self):
        self.server.app.state.security_settings = replace(self.config,stream_timeout=.02)
        closed = []
        class Endless:
            def __aiter__(self): return self
            async def __anext__(self):
                await asyncio.sleep(.005)
                return types.SimpleNamespace(choices=[])
            async def close(self): closed.append(True)
        with patch.object(self.server,'stream_respuesta_llm',AsyncMock(return_value=Endless())):
            response = self.client.post('/chat/stream',json={'mensaje':'Hola'})
        self.assertIn('"type": "error"',response.text)
        self.assertTrue(closed)
        self.assertTrue(self.server.app.state.active_requests.enter('chat',1))
        self.server.app.state.security_settings = replace(self.config,max_active_ai=1)
        try:
            response = self.client.post('/chat',json={'mensaje':''})
            self.assertEqual(response.status_code,429)
            self.assertEqual(response.json()['code'],'capacity_limited')
        finally:
            self.server.app.state.active_requests.leave('chat')
        closed = []
        class Stream:
            def __aiter__(self): return self
            async def __anext__(self): await asyncio.sleep(10)
            async def close(self): closed.append(True)
        self.server.app.state.security_settings = replace(self.config, provider_idle_timeout=.01)
        with patch.object(self.server,'stream_respuesta_llm',AsyncMock(return_value=Stream())):
            response = self.client.post('/chat/stream',json={'mensaje':'Hola'})
        events = [json.loads(l[6:]) for l in response.text.splitlines() if l.startswith('data: ')]
        self.assertEqual(events[-1]['type'],'error')
        self.assertTrue(closed)
        self.assertFalse(any(e['type']=='ui_action' for e in events))
        self.assertEqual(self.server.app.state.active_requests.counts['chat'],0)

    def test_slow_request_body_is_timed_out_before_parsing(self):
        self.server.app.state.security_settings = replace(self.config,body_timeout=.01)
        messages = []
        async def slow_receive():
            await asyncio.sleep(10)
            return {'type':'http.request','body':b'{}'}
        async def send(message): messages.append(message)
        async def endpoint(scope,receive,send): self.fail('No debe entrar al parser')
        scope = {'type':'http','app':self.server.app,'path':'/chat','method':'POST','scheme':'http',
                 'headers':[],'client':('test-peer',1)}
        asyncio.run(SecurityMiddleware(endpoint)(scope,slow_receive,send))
        self.assertEqual(messages[0]['status'],504)
        self.assertEqual(self.server.app.state.active_requests.counts['chat'],0)

    def test_liveness_readiness_and_sensitive_information(self):
        response = self.client.get('/health/ready')
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(all(response.json()['checks'].values()))
        self.assertNotIn('sqlite3',response.text)
        self.assertNotIn('Groq',response.text)
        repository = SQLiteRepository(Path(self.directory.name)/'empty.sqlite3')
        self.assertEqual(readiness(repository)['status'],'not_ready')
        self.assertEqual(self.client.get('/health/live').json()['status'],'alive')

    def test_action_count_and_argument_size_are_bounded(self):
        with self.assertRaises(ValueError): AssistantReply(structured_actions=[{}]*(MAX_ACTIONS+1))
        collector = ToolCallCollector()
        collector.feed([types.SimpleNamespace(index=0,function=types.SimpleNamespace(name='show_payment',arguments='x'*5000))])
        self.assertEqual(collector.finish(),[])
        self.assertTrue(collector.calls[0]['invalid'])

class StorageAndLimiterTests(unittest.TestCase):
    def test_production_admin_token_is_optional_but_must_be_strong_when_enabled(self):
        from commercial_runtime import admin_token
        for token in ['short','replace_with_random_private_token_at_least_32_characters']:
            with patch.dict('os.environ',{'APP_ENV':'production','ADMIN_API_TOKEN':token}):
                with self.assertRaises(ValueError): admin_token()
        with patch.dict('os.environ',{'APP_ENV':'production','ADMIN_API_TOKEN':''}):
            self.assertEqual(admin_token(),'')
    def test_sliding_window_expiry_and_memory_capacity(self):
        now = [0]
        store = MemoryRateLimitStore(max_keys=1,clock=lambda:now[0])
        self.assertEqual(store.consume('a',2,60),0)
        self.assertEqual(store.consume('a',2,60),0)
        self.assertEqual(store.consume('a',2,60),60)
        self.assertEqual(store.consume('b',2,60),60)
        now[0] = 61
        self.assertEqual(store.consume('b',2,60),0)
        self.assertEqual(len(store.entries),1)

    def test_consistent_backup_preserves_prices_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = SQLiteRepository(Path(directory)/'source.sqlite3')
            migrate(repo)
            seed_configuration(repo)
            service = CommercialService(repo)
            price = service.get('prices','turismo_000_inscripcion')
            service.save('prices',{**payload(price),'amount':'81'})
            target = repo.backup(Path(directory)/'snapshot.sqlite3')
            self.assertTrue(repo.health())
            backup = SQLiteRepository(target)
            self.assertEqual(CommercialService(backup).get('prices',price['id'])['amount'],'81')
            self.assertTrue(backup.health())
            # Un escritor tiene datos sin commit: el snapshot sólo debe incluir datos confirmados.
            with repo.transaction(write=True) as unit:
                unit.save('prices',price['id'],{**payload(price),'amount':'84'},'test')
                concurrent_snapshot = repo.backup(Path(directory)/'during_write.sqlite3')
                copy = SQLiteRepository(concurrent_snapshot)
                self.assertEqual(CommercialService(copy).get('prices',price['id'])['amount'],'81')
            with self.assertRaises(ValueError): repo.backup(target)
            with self.assertRaises(ValueError): repo.backup(repo.path)
            with repo.transaction() as unit:
                self.assertEqual(unit.db.execute('PRAGMA journal_mode').fetchone()[0],'wal')

    def test_production_configuration_rejects_wildcards_and_http(self):
        for origin in ['*','http://example.com','https://example.com/path','https://user:password@example.com']:
            with patch.dict('os.environ',{'APP_ENV':'production','ALLOWED_ORIGINS':origin}):
                with self.assertRaises(ValueError): SecuritySettings.from_env()
        with patch.dict('os.environ',{'APP_ENV':'production','ALLOWED_ORIGINS':'https://example.com'}):
            self.assertEqual(SecuritySettings.from_env().allowed_origins,('https://example.com',))

    def test_frontend_contains_no_provider_or_admin_secret(self):
        import re
        root = Path(__file__).resolve().parents[2] / 'avatar-kiosk/src'
        for path in root.rglob('*.js'):
            content = path.read_text(encoding='utf-8')
            self.assertNotIn('GROQ_API_KEY',content)
            self.assertNotIn('ADMIN_API_TOKEN',content)
            self.assertIsNone(re.search(r'gsk_[a-zA-Z0-9]{16,}|sk-[a-zA-Z0-9]{24,}',content))

if __name__ == '__main__': unittest.main()
