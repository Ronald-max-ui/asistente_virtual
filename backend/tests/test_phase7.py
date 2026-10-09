"""Bounded concurrent speech, metrics, retrieval and public caching regressions."""
import asyncio
import json
import types
import unittest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from test_phase1_api import load_server
from services.speech_pipeline import OrderedSpeechPipeline
from services.sentence_segmenter import SentenceSegmenter
from services.performance import PerformanceTrace, current_trace
from runtime_config import PerformanceSettings

class SpeechTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_synthesis_keeps_sentence_order_and_is_bounded(self):
        async def source():
            for i in range(20):yield str(i)
        active=peak=0
        async def synth(text):
            nonlocal active,peak
            active+=1;peak=max(peak,active)
            try:
                await asyncio.sleep(.02 if int(text)%2==0 else .001)
                return text.encode()
            finally:active-=1
        pipeline=OrderedSpeechPipeline(source(),synth,2,2)
        output=[]
        async for job in pipeline:output.append(await job.audio)
        self.assertEqual(output,[str(i).encode() for i in range(20)])
        self.assertEqual(peak,2);self.assertEqual(active,0)
        self.assertFalse(pipeline.tasks);self.assertTrue(pipeline.queue.empty())

    async def test_first_audio_does_not_wait_for_full_response(self):
        gate=asyncio.Event();closed=asyncio.Event()
        async def source():
            try:
                yield 'First.'
                await gate.wait()
                yield 'Last.'
            finally:closed.set()
        pipeline=OrderedSpeechPipeline(source(),AsyncMock(return_value=b'first'))
        iterator=pipeline.__aiter__();job=await asyncio.wait_for(anext(iterator),.5)
        self.assertEqual(await asyncio.wait_for(job.audio,.5),b'first')
        self.assertFalse(gate.is_set())
        await iterator.aclose();self.assertTrue(closed.is_set())

    async def test_backpressure_and_cancel_clear_all_pending_synthesis(self):
        produced=0;active=0;cancelled=0;gate=asyncio.Event()
        async def source():
            nonlocal produced
            for i in range(1000):produced+=1;yield str(i)
        async def synth(text):
            nonlocal active,cancelled
            active+=1
            try:await gate.wait();return b'a'
            except asyncio.CancelledError:cancelled+=1;raise
            finally:active-=1
        pipeline=OrderedSpeechPipeline(source(),synth,2,2)
        iterator=pipeline.__aiter__();await anext(iterator);await asyncio.sleep(.02)
        self.assertLessEqual(produced,6);self.assertEqual(active,2)
        self.assertLessEqual(len(pipeline.tasks),4)
        await iterator.aclose()
        self.assertEqual(active,0);self.assertEqual(cancelled,2)
        self.assertFalse(pipeline.tasks);self.assertTrue(pipeline.producer.done())
        self.assertTrue(pipeline.queue.empty())

    async def test_first_sentence_metric_does_not_measure_a_faster_second_sentence(self):
        from security.inputs import ChatInput
        server=load_server(real_session_auth=True);core=server.app.state.services.conversation
        identity=await core.sessions.bootstrap()
        async def stream():
            yield types.SimpleNamespace(choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content='First. Second. ',tool_calls=None))])
        async def synth(text):
            await asyncio.sleep(.05 if text=='First.' else .001)
            return b'audio'
        with patch.object(server,'stream_respuesta_llm',AsyncMock(return_value=stream())),patch.object(server,'generar_audio_bytes',synth):
            turn=await core.prepare(ChatInput(mensaje='Información institucional',session_id=identity['session_id'],mode='kiosk'),identity['session_token'])
            events=[event async for event in core.events(turn,server.app.state.security_settings)]
        self.assertGreaterEqual(turn.trace.values['tts_first_sentence_ms'],40)
        self.assertEqual(turn.trace.values['tts_sentences'],2)
        self.assertEqual([event['type'] for event in events],['text','audio','text','audio','done'])

    async def test_source_error_cleans_workers(self):
        async def source():
            yield 'First.'
            raise ValueError('private provider error')
        pipeline=OrderedSpeechPipeline(source(),AsyncMock(return_value=b'a'))
        with self.assertRaises(ValueError):
            async for job in pipeline:await job.audio
        self.assertFalse(pipeline.tasks)

    async def test_cancelled_conversation_under_prefetch_has_no_actions_or_history(self):
        from security.inputs import ChatInput
        server=load_server(real_session_auth=True);core=server.app.state.services.conversation
        identity=await core.sessions.bootstrap();synth_started=asyncio.Event();synth_cancelled=asyncio.Event()
        async def stream():
            try:
                for _ in range(100):
                    yield types.SimpleNamespace(choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content='Sentence. ',tool_calls=None))])
            finally:closed.set()
        async def synth(text):
            synth_started.set()
            try:await asyncio.sleep(30)
            finally:synth_cancelled.set()
        closed=asyncio.Event()
        with patch.object(server,'stream_respuesta_llm',AsyncMock(return_value=stream())),patch.object(server,'generar_audio_bytes',synth):
            turn=await core.prepare(ChatInput(mensaje='Muéstrame fotos',session_id=identity['session_id']),identity['session_token'])
            iterator=core.events(turn,server.app.state.security_settings)
            self.assertEqual((await anext(iterator))['type'],'text')
            await synth_started.wait();await iterator.aclose()
        self.assertTrue(closed.is_set());self.assertTrue(synth_cancelled.is_set())
        snapshot=core.sessions.repository.snapshot(identity['session_id'])
        self.assertEqual(snapshot['history'],[]);self.assertIsNone(snapshot['active_request_id'])
        self.assertFalse(core.sessions.tasks)

class SegmentAndMetricTests(unittest.TestCase):
    def test_segmenter_preserves_abbreviations_decimals_and_numbered_lists(self):
        segmenter=SentenceSegmenter();output=[]
        for chunk in ['El Sr. Pérez ve S/ 80.', '50. ¿Listo? ', '¡Vamos! 1. Requisitos. 2. Documentos. ']:
            output.extend(segmenter.feed(chunk))
        output.append(segmenter.finish())
        self.assertEqual(output[:-1],['El Sr. Pérez ve S/ 80.50.','¿Listo?','¡Vamos!','1. Requisitos.','2. Documentos.'])
        self.assertEqual(output[-1],'')

    def test_metrics_whitelist_logs_only_finite_numbers_with_request_correlation(self):
        trace=PerformanceTrace();trace.operation='generated-operation'
        trace.add('rag_ms',3);trace.add('prompt','secret');trace.add('rag_ms',float('nan'))
        with patch('services.performance.safe_event') as log:
            trace.report()
        self.assertEqual(log.call_args.kwargs['rag_ms'],3)
        self.assertNotIn('prompt',log.call_args.kwargs)
        self.assertIn('total_ms',log.call_args.kwargs)
        self.assertIsNone(current_trace.get())

    def test_manifest_cache_invalidates_on_write_and_has_short_maximum_age(self):
        import tempfile
        import time
        from pathlib import Path
        from services.knowledge_index import KnowledgeIndex
        from knowledge_config import IndexSettings
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);generation=root/'generation';generation.mkdir()
            manifest=generation/'manifest.json';manifest.write_text('{}')
            index=KnowledgeIndex(IndexSettings(root))
            with patch('services.knowledge_index.check_generation',return_value=({'status':'ready'},{'fixture':True})) as check:
                index._validated_manifest(generation);index._validated_manifest(generation)
                self.assertEqual(check.call_count,1)
                manifest.write_text('{"changed":true}')
                index._validated_manifest(generation);self.assertEqual(check.call_count,2)
                with patch('services.knowledge_index.time.monotonic',return_value=time.monotonic()+3):
                    index._validated_manifest(generation)
                self.assertEqual(check.call_count,3)

    def test_optional_warmup_runs_once_in_lifecycle_without_llm_or_rebuild(self):
        from dataclasses import replace
        server=load_server();services=server.app.state.services
        services.conversation.performance=replace(services.conversation.performance,knowledge_prewarm=True)
        warmup=AsyncMock();services.knowledge.warmup_call=warmup
        with TestClient(server.app) as client:
            client.get('/health');client.get('/api/config')
        warmup.assert_awaited_once()
        self.assertEqual(services.conversation.performance.tts_concurrency,2)

    def test_tts_configuration_is_small_and_validated(self):
        self.assertEqual(PerformanceSettings(),PerformanceSettings(2,2))
        for key,value in [('TTS_CONCURRENCY','5'),('TTS_PENDING_SENTENCES','9'),('TTS_CONCURRENCY','0')]:
            with patch.dict('os.environ',{key:value}),self.assertRaises(ValueError):PerformanceSettings.from_env()

    def test_public_config_revalidates_without_changing_dto_and_static_cache_is_public_only(self):
        server=load_server()
        with TestClient(server.app) as client:
            response=client.get('/api/config');etag=response.headers['etag']
            self.assertEqual(set(response.json()),{'assistant','avatar','visual','voice','features'})
            self.assertEqual(response.headers['cache-control'],'no-cache')
            self.assertEqual(client.get('/api/config',headers={'If-None-Match':etag}).status_code,304)
            avatar=response.json()['avatar']['url']
            self.assertEqual(client.get(avatar).headers['cache-control'],'public, no-cache')
            self.assertIn('immutable',client.get(avatar+'?v='+etag.strip('"')).headers['cache-control'])

    def test_clear_program_topics_skip_rewrite_but_ambiguous_followups_keep_it(self):
        from services.rag_service import needs_reformulation
        for question in ['Gastronomía virtual','Idiomas de Turismo','Requisitos Bartender','Duración Administración']:
            self.assertFalse(needs_reformulation(question),question)
        for question in ['¿Y cuánto cuesta?','¿Y virtual?','Administración']:
            self.assertTrue(needs_reformulation(question),question)

    def test_rewrite_skip_keeps_identical_retrieval_for_explicit_programme(self):
        from services.rag_service import buscar_contexto
        doc=types.SimpleNamespace(metadata={'titulo':'Gastronomía'},page_content='Formación presencial.')
        index=types.SimpleNamespace(search=lambda query,entity:[(doc,.1)])
        async def check():
            with patch('services.rag_service.reformular_query',AsyncMock(return_value='Gastronomía virtual')) as rewrite:
                previous=await buscar_contexto('Gastronomía virtual',[],index=index)
                after=await buscar_contexto('Gastronomía virtual',[{'role':'user','content':'Hola'}],index=index)
                self.assertEqual(previous,after);rewrite.assert_not_called()
                await buscar_contexto('¿Y virtual?',[{'role':'user','content':'Gastronomía'}],index=index)
                rewrite.assert_awaited_once()
        asyncio.run(check())

if __name__=='__main__':unittest.main()
