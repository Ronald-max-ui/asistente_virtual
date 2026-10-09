"""Architecture regressions: common policy, injected ports and safe boundaries."""
import asyncio
import ast
import io
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from fastapi import HTTPException, UploadFile
from test_phase1_api import load_server, ROOT
from domain.errors import SessionError, ProviderTimeout, ProviderUnavailable
from services.llm_protocol import AssistantReply, StreamAssembly
from services.providers import LLMDelta, GroqProvider, EdgeSpeechProvider, AcademicKnowledgeProvider
from services.pricing_service import PricingService, PricingPolicy
from services.action_service import ActionService, ActionContext
from services.commercial_service import CommercialService, payload
from persistence.sqlite_repository import SQLiteRepository
from migrate_commercial import migrate, seed_configuration
from app_services import build_services
from runtime_config import SessionSettings, sqlite_timeout

async def chunks(text):
    yield types.SimpleNamespace(choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content=text))])

class CommonCoreTests(unittest.TestCase):
    def test_both_transports_use_one_prepare_policy_and_commit(self):
        server = load_server()
        core = server.app.state.services.conversation
        actions = [{'type':'show_gallery','resource_id':'gastronomia_talleres'}]
        async def stream():
            yield types.SimpleNamespace(choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content='Aquí tienes la imagen.',
                tool_calls=[types.SimpleNamespace(index=0,function=types.SimpleNamespace(name='show_gallery',arguments='{"resource_id":"gastronomia_talleres"}'))]))])
        with patch.object(core,'prepare', wraps=core.prepare) as prepare, patch.object(core,'resolve_actions', wraps=core.resolve_actions) as policy, \
             patch.object(core,'commit', wraps=core.commit) as commit, patch.object(server,'generar_respuesta_llm',AsyncMock(return_value=AssistantReply(assistant_text='Aquí tienes la imagen.',structured_actions=actions))), \
             patch.object(server,'stream_respuesta_llm',AsyncMock(return_value=stream())), patch.object(server,'generar_audio_bytes',AsyncMock(return_value=b'audio')), TestClient(server.app) as client:
            standard = client.post('/chat',json={'mensaje':'Muéstrame fotos','session_id':'core-json'}).json()
            response = client.post('/chat/stream',json={'mensaje':'Muéstrame fotos','session_id':'core-sse'})
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
        self.assertEqual(prepare.call_count,2)
        self.assertEqual(policy.call_count,2)
        self.assertEqual(commit.call_count,2)
        self.assertEqual(events[-1]['full_text'],standard['texto'])
        self.assertEqual([event['action'] for event in events if event['type']=='ui_action'],standard['actions'])
        self.assertEqual([event['type'] for event in events],['text','audio','ui_action','done'])

    def test_domain_errors_map_at_http_boundary_without_private_details(self):
        server=load_server()
        with TestClient(server.app,raise_server_exceptions=False) as client:
            for error,status,code in [(SessionError('session_busy'),409,'session_busy'),
                (SessionError('session_unauthorized',401),401,'session_unauthorized'),
                (ProviderTimeout(),503,None),(ProviderUnavailable(),502,None),
                (SessionError('private-path SECRET SELECT',409),409,None)]:
                with patch.object(server.app.state.services.conversation,'prepare',AsyncMock(side_effect=error)):
                    response=client.post('/chat',json={'mensaje':'Hola','session_id':'mapping'})
                self.assertEqual(response.status_code,status)
                if code: self.assertEqual(response.json()['code'],code)
                self.assertNotIn('SECRET',response.text)
                self.assertNotIn('SELECT',response.text)
        self.assertNotIsInstance(SessionError('session_busy'),HTTPException)

    def test_composition_injects_catalog_and_providers_without_sdk_or_global_price(self):
        with tempfile.TemporaryDirectory() as directory:
            repo=SQLiteRepository(Path(directory)/'commercial.sqlite3')
            self.assertFalse(migrate(repo)['rejected'])
            seed_configuration(repo)
            commercial=CommercialService(repo)
            price=next(p for p in commercial.list('prices') if p['program']=='gastronomia' and p['concept']=='inscripcion')
            commercial.save('prices',{**payload(price),'amount':'123'})
            pricing=PricingService(repository=repo)
            server=load_server()
            text='La inscripción cuesta 999 soles.'
            llm=GroqProvider(AsyncMock(return_value=AssistantReply(assistant_text=text,structured_actions=[{'type':'show_payment','program':'gastronomia','concept':'inscripcion'}])),AsyncMock(return_value=chunks(text)))
            speech=EdgeSpeechProvider(AsyncMock(return_value=b'audio'))
            knowledge=AcademicKnowledgeProvider(AsyncMock(return_value='El precio histórico era 888 soles.'))
            configuration=types.SimpleNamespace(session_ttl_seconds=90,session_cleanup_interval_seconds=60)
            composed=build_services(configuration,session=server.session_manager,pricing=pricing,llm=llm,speech=speech,knowledge=knowledge,voucher_directory=Path(directory)/'vouchers')
            server.app.state.services=composed
            server.app.state.commercial_service=commercial
            self.assertIs(composed.actions.pricing,pricing)
            self.assertIs(composed.operational.pricing,pricing)
            self.assertIs(composed.conversation.pricing_policy.service,pricing)
            self.assertIsNone(composed.provider_client)
            with TestClient(server.app) as client:
                response=client.post('/chat',json={'mensaje':'Quiero pagar la inscripción de Gastronomía','session_id':'injected'})
                public=client.get('/api/config').json()
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['actions'][0]['amount'],'123')
            self.assertIn('123 soles',response.json()['texto'])
            self.assertNotIn('999',response.json()['texto'])
            self.assertNotIn('888',response.json()['texto'])
            self.assertEqual(set(public),{'assistant','avatar','visual','voice','features'})
            self.assertTrue(llm.complete_call.await_count)
            self.assertTrue(knowledge.search_call.await_count)

    def test_rejected_upload_closes_file_and_never_writes(self):
        server=load_server()
        from security.inputs import VoucherInput
        upload=UploadFile(io.BytesIO(b'not-read'),filename='a.png')
        form=VoucherInput(monto='0',carrera='gastronomia',concepto='matricula')
        result=asyncio.run(server.app.state.services.vouchers.submit(form,upload,None,server.app.state.security_settings))
        self.assertEqual(result.status_code,409)
        self.assertTrue(upload.file.closed)
        self.assertEqual(list(Path(server._VOUCHERS_DIR).iterdir()),[])

    def test_closing_sse_transport_releases_lease_before_pending_audio_actions(self):
        async def check():
            server=load_server(real_session_auth=True)
            identity=await server.session_manager.bootstrap()
            request=types.SimpleNamespace(headers={'X-Session-Token':identity['session_token']})
            from security.inputs import ChatInput
            stream=chunks('Información institucional.')
            with patch.object(server,'stream_respuesta_llm',AsyncMock(return_value=stream)), patch.object(server,'generar_audio_bytes',AsyncMock(return_value=b'a')):
                response=await server.responder_streaming(ChatInput(mensaje='Hola',session_id=identity['session_id']),request)
                first=await anext(response.body_iterator)
                self.assertIn('"type": "text"',first)
                await response.body_iterator.aclose()
            snapshot=server.session_manager.repository.snapshot(identity['session_id'])
            self.assertIsNone(snapshot['active_request_id'])
            self.assertEqual(snapshot['history'],[])
            self.assertEqual(server.session_manager.tasks,{})
        asyncio.run(check())

    def test_speech_adapter_uses_injected_configuration(self):
        from services.tts_service import generar_audio_bytes
        async def stream(): yield {'type':'audio','data':b'speech'}
        communicate=types.SimpleNamespace(stream=stream)
        from security.config import SecuritySettings
        configuration=types.SimpleNamespace(tts_voice='test-voice',tts_rate='+2%',security=SecuritySettings())
        with patch('services.tts_service.edge_tts.Communicate',return_value=communicate) as create:
            self.assertEqual(asyncio.run(generar_audio_bytes('Hola',configuration=configuration)),b'speech')
        self.assertEqual(create.call_args.args,('Hola','test-voice'))
        self.assertEqual(create.call_args.kwargs['rate'],'+2%')

    def test_new_core_does_not_depend_on_http_or_sql_adapters(self):
        for name in ('domain/pricing.py','domain/errors.py','services/conversation_service.py'):
            tree=ast.parse((ROOT/name).read_text(encoding='utf-8'))
            imports=[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
            self.assertFalse(any(m and m.startswith(('fastapi','starlette','persistence.sqlite')) for m in imports),name)
        server=ast.parse((ROOT/'server.py').read_text(encoding='utf-8'))
        self.assertFalse(any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in ('post','get') for n in ast.walk(server)))

class AssemblyAndConfigurationTests(unittest.TestCase):
    def test_fragmented_legacy_tags_are_never_spoken_and_truncation_blocks_actions(self):
        assembly=StreamAssembly('Muéstrame fotos',[])
        self.assertEqual(assembly.accept(LLMDelta('[[ACT')),[])
        self.assertEqual(assembly.accept(LLMDelta('ION:SHOW_GALLERY:gastronomia_talleres]] Aquí tienes una foto. ')),[' Aquí tienes una foto.'])
        text,actions=assembly.finish()
        self.assertEqual(text,'')
        self.assertEqual(actions[0]['type'],'show_gallery')
        assembly=StreamAssembly('Muéstrame fotos',[])
        assembly.accept(LLMDelta('[[ACTION:SHOW_GALLERY:gastronomia_talleres]]',truncated=True))
        self.assertEqual(assembly.finish()[1],[])

    def test_sdk_deltas_are_normalized_in_provider_adapter(self):
        provider=GroqProvider(None,None)
        delta=provider.delta(types.SimpleNamespace(choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content='Hola',tool_calls=None),finish_reason='length')]))
        self.assertEqual(delta,LLMDelta('Hola',None,True))
        self.assertEqual(provider.delta(types.SimpleNamespace(choices=[])),LLMDelta())

    def test_configuration_validates_private_paths_limits_and_sqlite_timeout(self):
        for key,value in [('SESSION_PERSISTED_TURNS','0'),('SESSION_LIFETIME_SECONDS','-1'),('RUNTIME_DATABASE_PATH','static/runtime.sqlite3')]:
            with patch.dict('os.environ',{key:value}),self.assertRaises(ValueError): SessionSettings.from_env()
        for value in ('0','nan','31'):
            with patch.dict('os.environ',{'SQLITE_BUSY_TIMEOUT_SECONDS':value}),self.assertRaises(ValueError): sqlite_timeout()
        self.assertTrue(SessionSettings.from_env().path.is_absolute())
