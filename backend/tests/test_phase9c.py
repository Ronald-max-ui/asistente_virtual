"""Personalization/security/voice E2E, using exclusively temporary persistence."""
import unittest,asyncio,io,json
from unittest.mock import patch
from PIL import Image
import test_phase9a as previous
from test_phase1_api import valid_png
from services.providers import ConfiguredEdgeSpeechProvider
from services.voice_service import VoiceService
from domain.voice import VoiceConfig
from backup_personalization import backup_personalization,verify_backup
class PersonalizationTests(unittest.TestCase):
    setUp=previous.AdminTests.setUp
    create=previous.AdminTests.create
    login=previous.AdminTests.login
    csrf=previous.AdminTests.csrf
    def upload(self,filename='logo.png',content=None,mime='image/png',purpose='logo'):
        return self.client.post('/api/admin/branding-assets',data={'purpose':purpose},files={'file':(filename,valid_png() if content is None else content,mime)},headers=self.csrf())
    def save(self,**changes):
        response=self.client.get('/api/admin/settings');body=response.json();body.update(changes)
        return self.client.put('/api/admin/settings',json=body,headers={**self.csrf(),'If-Match':response.headers['etag']})
    def configure_speech(self):
        self.calls=[]
        async def audio(text,voice=None):self.calls.append({'text':text,'voice':voice});return b'synthetic-audio'
        speech=ConfiguredEdgeSpeechProvider(audio,VoiceService(self.repo));self.server.app.state.services.speech=speech;self.server.app.state.services.conversation.speech=speech;return speech
    def test_branding_end_to_end_etag_public_whitelist_audit(self):
        self.login();old=self.client.get('/api/config').headers['etag'];upload=self.upload();self.assertEqual(upload.status_code,201,upload.text);asset=upload.json()
        self.assertEqual(self.save(assistant_name='Instituto Asistente',primary_color='#135790',initial_message='Hola. Te ayudo.',logo_url=asset['url'],voice={'voice_id':'es-PE-AlexNeural'}).status_code,200)
        public=self.client.get('/api/config');data=public.json();self.assertNotEqual(old,public.headers['etag']);self.assertEqual(data['assistant']['name'],'Instituto Asistente');self.assertEqual(data['voice']['voice_id'],'es-PE-AlexNeural')
        self.assertRegex(data['assistant']['logo_url'],r'\?v=[a-f0-9]{64}$');self.assertEqual(self.client.get(data['assistant']['logo_url']).status_code,200)
        self.assertEqual(self.client.get('/api/config',headers={'If-None-Match':public.headers['etag']}).status_code,304)
        self.assertNotIn('created_by',public.text);self.assertNotIn('extensions',data)
        audit=self.client.get('/api/admin/audit?resource_type=settings').json();entry=next(a for a in audit if a['action']=='settings.save');self.assertEqual(entry['after']['voice']['voice_id'],'es-PE-AlexNeural');self.assertEqual(entry['after']['initial_message'],'Hola. Te ayudo.')
    def test_secure_assets_and_false_formats(self):
        self.login()
        for name,content,mime in [('logo.jpg',valid_png(),'image/png'),('logo.png',valid_png(),'image/jpeg'),('../logo.png',valid_png(),'image/png'),('logo.png.exe',valid_png(),'image/png'),('logo.svg',b'<svg onload="alert(1)"/>','image/svg+xml'),('logo.png',b'\x89PNG\r\n\x1a\ncorrupt','image/png')]:
            with self.subTest(name=name,mime=mime):self.assertEqual(self.upload(name,content,mime).status_code,400)
        self.assertEqual(self.upload(content=b'x'*(2*1024*1024+1)).status_code,413)
        self.assertEqual(self.client.get('/static/branding/unknown.png').status_code,404)
    def test_dimensions_favicon_and_public_headers(self):
        self.login();out=io.BytesIO();Image.new('RGB',(2100,1)).save(out,format='PNG');self.assertEqual(self.upload(content=out.getvalue()).status_code,400)
        out=io.BytesIO();Image.new('RGB',(10,11)).save(out,format='PNG');self.assertEqual(self.upload(content=out.getvalue(),purpose='favicon').status_code,422)
        asset=self.upload(purpose='favicon').json();self.assertEqual(self.save(favicon_url=asset['url']).status_code,200)
        response=self.client.get(asset['url']);self.assertEqual(response.headers['content-type'],'image/png');self.assertIn('immutable',response.headers['cache-control']);self.assertEqual(response.headers['x-content-type-options'],'nosniff')
        self.assertEqual(self.save(logo_url=asset['url']).status_code,409)
        self.assertEqual(self.save(logo_url='/static/branding/'+'0'*32+'.png').status_code,409)
        self.assertEqual(self.save(logo_url='https://evil.example/logo.png').status_code,422)
    def test_upload_permissions_and_csrf(self):
        self.create('reader','solo_lectura');self.login('reader');self.assertEqual(self.upload().status_code,403)
        self.login();self.assertEqual(self.client.post('/api/admin/branding-assets',data={'purpose':'logo'},files={'file':('logo.png',valid_png(),'image/png')},headers={'Origin':previous.ORIGIN}).status_code,403)
    def test_upload_database_failure_cleans_file(self):
        self.login();branding=self.server.app.state.services.branding
        with patch.object(branding.repository,'add',side_effect=RuntimeError('synthetic')):
            self.assertEqual(self.upload().status_code,500)
        self.assertFalse(list(branding.root.glob('*')))
    def test_voice_validation_and_fixed_preview_limit(self):
        self.login();self.configure_speech()
        for value in [{'voice_id':'evil'}, {'voice_id':'es-PE-CamilaNeural','secret':'x'}, {'rate':'+51%'},{'pitch':'<speak>'}]:self.assertEqual(self.save(voice=value).status_code,422)
        for _ in range(5):self.assertEqual(self.client.post('/api/admin/voice-preview',json=VoiceConfig().model_dump(),headers=self.csrf()).status_code,200)
        self.assertEqual(self.client.post('/api/admin/voice-preview',json=VoiceConfig().model_dump(),headers=self.csrf()).status_code,429)
        self.assertTrue(all(c['text']=='Hola. Estoy lista para ayudarte.' for c in self.calls))
        self.assertEqual(self.client.post('/api/admin/voice-preview',json={'text':'arbitrary'},headers=self.csrf()).status_code,422)
    def test_voice_end_to_end_new_conversation_uses_selection(self):
        self.login();self.configure_speech();self.server.generar_respuesta_llm.return_value='Información institucional.';self.assertEqual(self.save(voice={'voice_id':'es-PE-AlexNeural','rate':'+5%'}).status_code,200)
        bootstrap=self.client.post('/api/session',json={}).json();response=self.client.post('/chat',json={'mensaje':'Hola','session_id':bootstrap['session_id'],'persona':'info','mode':'web'},headers={'X-Session-Token':bootstrap['session_token']})
        self.assertEqual(response.status_code,200,response.text);self.assertTrue(self.calls);self.assertEqual(self.calls[0]['voice']['voice_id'],'es-PE-AlexNeural');self.assertEqual(self.calls[0]['voice']['rate'],'+5%')
        self.assertEqual(self.save(voice={'enabled':False}).status_code,200)
        response=self.client.post('/chat',json={'mensaje':'Hola','session_id':bootstrap['session_id'],'persona':'info','mode':'kiosk'},headers={'X-Session-Token':bootstrap['session_token']});self.assertEqual(response.status_code,200);self.assertEqual(response.json()['audio_b64'],'')
    def test_voice_snapshot_stable_and_legacy_preserved(self):
        speech=self.configure_speech();old=speech.snapshot();self.commercial.save_settings({**self.commercial.settings(),'voice':{'voice_id':'es-PE-AlexNeural'}})
        asyncio.run(speech.synthesize_configured('Synthetic',old));self.assertEqual(self.calls[-1]['voice']['voice_id'],old['voice_id']);self.assertNotEqual(speech.snapshot()['voice_id'],old['voice_id'])
        with self.repo.transaction(write=True) as unit:unit.save_settings({'voice':{}},'test')
        service=VoiceService(self.repo);service.initialize('unsupported-legacy','+3%');self.assertEqual(service.public()['status'],'degraded')
        with self.repo.transaction() as unit:self.assertEqual(unit.settings()['voice']['voice_id'],'unsupported-legacy')
    def test_plain_text_color_and_optimistic_conflict(self):
        self.login()
        for changes in [{'primary_color':'red'},{'primary_color':'#fff'},{'initial_message':'<script>x</script>'},{'initial_message':'x'*501}]:self.assertEqual(self.save(**changes).status_code,422)
        old=self.client.get('/api/admin/settings');self.assertEqual(self.save(assistant_name='Current').status_code,200)
        self.assertEqual(self.client.put('/api/admin/settings',json=old.json(),headers={**self.csrf(),'If-Match':old.headers['etag']}).status_code,409)
    def test_backup_includes_registry_assets_users_and_audit(self):
        self.login();asset=self.upload().json();self.save(logo_url=asset['url']);branding=self.server.app.state.services.branding
        target=backup_personalization(self.repo.path,branding.root,self.root/'backup');self.assertEqual(verify_backup(target)['assets'],1)
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(target/'commercial.sqlite3')) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM admin_users').fetchone()[0],1);self.assertGreater(db.execute('SELECT COUNT(*) FROM admin_audit_log').fetchone()[0],0)
        file=next((target/'branding').iterdir());file.write_bytes(b'changed')
        with self.assertRaises(ValueError):verify_backup(target)
    def test_backup_missing_file_fails_without_partial_destination(self):
        self.login();self.upload();branding=self.server.app.state.services.branding;next(branding.root.iterdir()).unlink()
        with self.assertRaises(ValueError):backup_personalization(self.repo.path,branding.root,self.root/'missing-backup')
        self.assertFalse((self.root/'missing-backup').exists())

    def test_edge_sdk_receives_selected_parameters(self):
        from services.tts_service import generar_audio_bytes
        from security.config import SecuritySettings
        from types import SimpleNamespace
        class Stream:
            async def stream(self):yield {'type':'audio','data':b'synthetic'}
        voice=VoiceConfig(voice_id='es-PE-AlexNeural',rate='+5%',pitch='-2Hz',volume='-5%').model_dump()
        with patch('services.tts_service.edge_tts.Communicate',return_value=Stream()) as create:
            result=asyncio.run(generar_audio_bytes('Frase fija',configuration=SimpleNamespace(security=SecuritySettings()),voice=voice))
        self.assertEqual(result,b'synthetic');self.assertEqual(create.call_args.args,('Frase fija','es-PE-AlexNeural'));self.assertEqual(create.call_args.kwargs['pitch'],'-2Hz');self.assertEqual(create.call_args.kwargs['volume'],'-5%')
