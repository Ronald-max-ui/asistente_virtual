"""Real concurrent SQLite claims + HTTP/protocol cancellation regressions."""
import asyncio
import json
import sqlite3
import tempfile
import threading
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import AsyncMock, patch
import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_phase1_api import load_server, valid_png
from session_manager import SessionManager, token_digest
from persistence.runtime_repository import RuntimeConflict
from persistence.sqlite_runtime_repository import SQLiteRuntimeRepository
from services.llm_protocol import AssistantReply


LEAD = dict(name='Test', whatsapp='999888777', program='turismo', modality=None, origin='web', notes='')
QUOTE = dict(program='turismo', modality=None, shift=None, concept='inscripcion', amount='80',
             currency='PEN', campaign='base', campaign_id=None)


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 1000
        self.repo = SQLiteRuntimeRepository(Path(self.temp.name)/'runtime.sqlite3',
            inactivity=60, lifetime=300, max_turns=2, max_chars=2000, lease=30, clock=lambda:self.now)
        self.repo.create_session('one', token_digest('secret'))
        self.repo.create_session('two', token_digest('other'))

    def test_real_concurrent_claims_from_independent_connections(self):
        barrier = threading.Barrier(8)
        def claim(index):
            independent = SQLiteRuntimeRepository(self.repo.path, clock=lambda:self.now)
            barrier.wait()
            try: return independent.begin('one','sales')[0]
            except RuntimeConflict: return None
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(claim, range(8)))
        self.assertEqual(sum(bool(result) for result in results), 1)
        rid = next(result for result in results if result)
        self.repo.finish('one', rid, 'Question', 'Answer', [])
        self.repo.release('one',rid)
        self.assertEqual(len(self.repo.snapshot('one')['history']),2)

    def test_distinct_sessions_can_claim_concurrently(self):
        barrier = threading.Barrier(2)
        def claim(sid):
            barrier.wait()
            return self.repo.begin(sid,'info')[0]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim,['one','two']))
        self.assertEqual(len(set(results)),2)

    def test_replace_cancel_late_finish_and_old_release(self):
        old,_=self.repo.begin('one','info')
        new,_=self.repo.begin('one','sales',replace=True)
        for method in ('current','finish'):
            with self.assertRaises(RuntimeConflict):
                getattr(self.repo,method)('one',old,*(['old','old',[]] if method=='finish' else []))
        self.repo.release('one',old)
        self.repo.current('one',new)
        self.assertEqual(self.repo.snapshot('one')['history'],[])
        self.repo.cancel('one',old)
        self.repo.current('one',new)
        self.repo.cancel('one',new)
        with self.assertRaises(RuntimeConflict): self.repo.current('one',new)

    def test_history_count_size_and_restart(self):
        for index in range(6):
            rid,_=self.repo.begin('one','info')
            self.repo.finish('one',rid,str(index),'a'*200,[])
            self.repo.release('one',rid)
        restarted=SQLiteRuntimeRepository(self.repo.path,clock=lambda:self.now)
        history=restarted.snapshot('one')['history']
        self.assertEqual(len(history),4)
        self.assertEqual(history[0]['content'],'4')
        rid,_=self.repo.begin('one','info')
        self.repo.finish('one',rid,'x'*1000,'y'*1500,[])
        self.repo.release('one',rid)
        self.assertLessEqual(sum(len(m['content']) for m in self.repo.snapshot('one')['history']),2000)

    def test_expiration_preserves_commercial_links_revokes_credentials(self):
        lead=self.repo.save_lead('one',LEAD,'lead-key')
        rid,_=self.repo.begin('one','sales')
        self.now += 61
        self.assertEqual(len(self.repo.cleanup()),2)
        with self.assertRaises(RuntimeConflict): self.repo.current('one',rid)
        with self.assertRaises(RuntimeConflict): self.repo.authorize('one',token_digest('secret'))
        self.assertEqual(self.repo.get_record('leads',lead['lead_id'])['session_id'],'one')
        self.assertTrue(self.repo.health())

    def test_absolute_lifetime_and_orphan_lease(self):
        rid,_=self.repo.begin('one','sales')
        self.now+=31
        new,_=self.repo.begin('one','sales')
        self.assertNotEqual(new,rid)
        self.repo.release('one',new)
        for step in range(5):
            self.now+=50
            new,_=self.repo.begin('one','sales')
            self.repo.release('one',new)
        self.now=1301
        with self.assertRaises(RuntimeConflict): self.repo.begin('one','sales')

    def test_idempotent_lead_retries_concurrent_and_conflicting_payload(self):
        barrier=threading.Barrier(6)
        def save(index):
            barrier.wait()
            return self.repo.save_lead('one',LEAD,'same')
        with ThreadPoolExecutor(max_workers=6) as pool:
            results=list(pool.map(save,range(6)))
        self.assertEqual(len({r['lead_id'] for r in results}),1)
        with self.assertRaises(RuntimeConflict): self.repo.save_lead('one',{**LEAD,'whatsapp':'777888999'},'same')
        self.assertEqual(self.repo.snapshot('one')['lead_id'],results[0]['lead_id'])
        with self.assertRaises(RuntimeConflict): self.repo.save_lead('one',LEAD,'different')

    def test_voucher_link_retry_reset_and_backup(self):
        lead=self.repo.save_lead('one',LEAD,'lead')
        calls=[]
        def write():
            calls.append(1)
            return 'voucher','voucher.png'
        first=self.repo.save_voucher('one',QUOTE,'digest','voucher-key',write,lambda _:None,lead['lead_id'])
        second=self.repo.save_voucher('one',QUOTE,'digest','voucher-key',write,lambda _:None,lead['lead_id'])
        self.assertEqual(first,second)
        self.assertEqual(len(calls),1)
        voucher=self.repo.get_record('vouchers',first['voucher_id'])
        self.assertEqual((voucher['lead_id'],voucher['amount'],voucher['status']), (lead['lead_id'],'80','pending_review'))
        with self.assertRaises(RuntimeConflict): self.repo.save_voucher('two',QUOTE,'wrong','key',write,lambda _:None,lead['lead_id'])
        rid,_=self.repo.begin('one','sales')
        result,_=self.repo.cancel('one',reset=True,key='reset')
        new,_=self.repo.begin('one','sales')
        self.assertEqual(self.repo.cancel('one',reset=True,key='reset')[0],result)
        self.repo.current('one',new)  # replay must not reset a subsequent interaction
        self.assertEqual(self.repo.snapshot('one')['lead_id'],lead['lead_id'])
        self.assertIsNotNone(self.repo.get_record('vouchers','voucher'))
        backup=self.repo.backup(Path(self.temp.name)/'backup.sqlite3')
        restored=SQLiteRuntimeRepository(backup,clock=lambda:self.now)
        self.assertEqual(restored.snapshot('one')['lead_id'],lead['lead_id'])
        with self.assertRaises(ValueError): self.repo.backup(backup)

    def test_voucher_rollback_cleans_written_file(self):
        removed=[]
        # A duplicate primary key simulates failure after writing the image.
        self.repo.save_voucher(None,QUOTE,'first','one',lambda:('duplicate','first.png'),removed.append)
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.save_voucher(None,QUOTE,'second','two',lambda:('duplicate','second.png'),removed.append)
        self.assertEqual(removed,['second.png'])

    def test_concurrent_voucher_retries_write_one_file_and_one_record(self):
        barrier = threading.Barrier(5)
        writes = []
        def save(index):
            barrier.wait()
            return self.repo.save_voucher('one',QUOTE,'same','voucher-key',
                lambda: (writes.append(1) or 'voucher', 'voucher.png'),lambda _:None)
        with ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(save, range(5)))
        self.assertEqual(len(writes),1)
        self.assertEqual(len({result['voucher_id'] for result in results}),1)

    def test_changed_lead_during_upload_is_rejected_before_writing(self):
        self.repo.save_lead('one',LEAD,'lead-key')
        with self.assertRaises(RuntimeConflict):
            self.repo.save_voucher('one',QUOTE,'digest','key',
                lambda:self.fail('must not write'),lambda _:None,None,True)

    def test_backup_package_contains_consistent_db_and_images(self):
        from backup_runtime import backup_runtime
        root = Path(self.temp.name)/'vouchers'
        root.mkdir()
        (root/'voucher.png').write_bytes(valid_png())
        self.repo.save_voucher('one',QUOTE,'digest','key',lambda:('voucher','voucher.png'),lambda _:None)
        target = backup_runtime(self.repo,root,Path(self.temp.name)/'package')
        self.assertEqual((target/'vouchers/voucher.png').read_bytes(),valid_png())
        self.assertEqual(len(json.loads((target/'manifest.json').read_text())['vouchers']),1)
        with self.assertRaises(ValueError): backup_runtime(self.repo,root,target)
        (root/'voucher.png').unlink()
        with self.assertRaises(ValueError): backup_runtime(self.repo,root,Path(self.temp.name)/'broken')
        self.assertFalse((Path(self.temp.name)/'broken').exists())

    def test_funnel_has_only_backend_transitions_and_valid_statuses(self):
        self.assertEqual(self.repo.snapshot('one')['funnel_stage'],'discovery')
        rid,_=self.repo.begin('one','info')
        self.repo.finish('one',rid,'hello','information',[])
        self.repo.release('one',rid)
        self.assertEqual(self.repo.snapshot('one')['funnel_stage'],'value')
        self.repo.save_lead('one',LEAD,'key')
        self.assertEqual(self.repo.snapshot('one')['funnel_stage'],'lead_captured')
        rid,_=self.repo.begin('one','sales')
        self.repo.finish('one',rid,'pay','approved quote',[{'type':'show_payment'}])
        self.assertEqual(self.repo.snapshot('one')['funnel_stage'],'closing')
        with self.assertRaises(sqlite3.IntegrityError), self.repo.transaction() as db:
            db.execute("UPDATE sessions SET funnel_stage='paid' WHERE session_id='one'")


class SessionApiTests(unittest.TestCase):
    def setUp(self):
        self.server=load_server(real_session_auth=True)
        self.client=TestClient(self.server.app,raise_server_exceptions=False)
        self.addCleanup(self.client.close)
        data=self.client.post('/api/session',json={}).json()
        self.sid=data['session_id']
        self.headers={'X-Session-Token':data['session_token']}

    def test_id_is_not_authorization_and_credentials_not_exposed(self):
        for path in ('/chat','/chat/stream','/reset-session'):
            self.assertEqual(self.client.post(path,json={'mensaje':'hello','session_id':self.sid}).status_code,401)
        self.assertEqual(self.client.post('/api/session',json={'session_id':self.sid}).status_code,409)
        response=self.client.post('/api/session',json={'session_id':self.sid},headers=self.headers)
        self.assertEqual(response.status_code,200)
        for path in ('/health/ready','/api/config'):
            self.assertNotIn(self.headers['X-Session-Token'],self.client.get(path).text)
        self.assertNotIn(self.headers['X-Session-Token'],str(self.server.session_manager.repository.snapshot(self.sid)))

    def test_lead_voucher_idempotence_restart_and_reset_http(self):
        lead_data={'session_id':self.sid,'nombre':'Test','whatsapp':'999888777','carrera':'turismo'}
        headers={**self.headers,'Idempotency-Key':'lead-key'}
        one=self.client.post('/api/leads',data=lead_data,headers=headers)
        two=self.client.post('/api/leads',data=lead_data,headers=headers)
        self.assertEqual(one.status_code,200,one.text)
        self.assertEqual(one.json(),two.json())
        self.server.session_manager=SessionManager(repository=SQLiteRuntimeRepository(self.server.session_manager.repository.path))
        payload={'session_id':self.sid,'carrera':'turismo','concepto':'inscripcion','monto':'80'}
        def upload(**changes):
            return self.client.post('/api/vouchers',data={**payload,**changes},headers={**self.headers,'Idempotency-Key':'voucher-key'},
                files={'imagen':('voucher.png',valid_png(),'image/png')})
        first,second=upload(),upload()
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(first.json(),second.json())
        repo=self.server.session_manager.repository
        voucher=repo.get_record('vouchers',first.json()['voucher_id'])
        self.assertEqual(voucher['lead_id'],one.json()['lead_id'])
        self.assertEqual(voucher['status'],'pending_review')
        self.assertEqual(upload(lead_id='a'*32).status_code,409)
        self.assertEqual(self.client.post('/reset-session',json={'mensaje':'','session_id':self.sid},headers=self.headers).status_code,200)
        self.assertEqual(repo.snapshot(self.sid)['lead_id'],one.json()['lead_id'])
        self.assertIsNotNone(repo.get_record('vouchers',first.json()['voucher_id']))

    def test_payment_context_request_ids_and_chat_retries(self):
        reply=AssistantReply(assistant_text='Información.', structured_actions=[{'type':'show_payment','program':'turismo','concept':'inscripcion','amount':'999'}])
        with patch.object(self.server,'generar_respuesta_llm',AsyncMock(return_value=reply)), patch.object(self.server,'generar_audio_bytes',AsyncMock(return_value=b'a')):
            body={'mensaje':'Quiero pagar la inscripción de Turismo','session_id':self.sid,'idempotency_key':'chat-key'}
            response=self.client.post('/chat',json=body,headers=self.headers)
            self.assertEqual(response.status_code,200)
            self.assertRegex(response.json()['request_id'],r'^[a-f0-9]{32}$')
            self.assertEqual(response.json()['actions'],[])
            self.assertEqual(self.client.post('/chat',json=body,headers=self.headers).status_code,409)

    def test_new_headers_are_allowed_and_runtime_readiness_is_safe(self):
        response=self.client.options('/chat/stream', headers={'Origin':'http://localhost:5173',
            'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'x-session-token,idempotency-key'})
        self.assertEqual(response.status_code,200)
        with patch.object(self.server.session_manager.repository,'health',return_value=False):
            readiness=self.client.get('/health/ready')
        self.assertEqual(readiness.status_code,503)
        self.assertFalse(readiness.json()['checks']['runtime'])
        self.assertNotIn(self.sid,readiness.text)
        self.assertNotIn('runtime.sqlite3',readiness.text)

    def test_invalid_cancel_key_is_validation_error_not_internal_error(self):
        response=self.client.post('/api/session/cancel',json={'session_id':self.sid},
            headers={**self.headers,'Idempotency-Key':'../invalid'})
        self.assertEqual(response.status_code,422)

    def test_expiration_http_rejects_lead_and_chat_without_leaking_data(self):
        repo=self.server.session_manager.repository
        repo.clock=lambda:10**12
        for path in ('/chat','/chat/stream','/reset-session'):
            response=self.client.post(path,json={'mensaje':'Hola','session_id':self.sid},headers=self.headers)
            self.assertEqual(response.status_code,410)
            self.assertEqual(response.json()['code'],'session_expired')

    def test_real_credentials_sse_order_and_all_contexts(self):
        async def chunks():
            yield types.SimpleNamespace(choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content='Aquí tienes información.',tool_calls=None))])
        for mode in ('web','kiosk'):
            for persona in ('info','sales'):
                with patch.object(self.server,'stream_respuesta_llm',AsyncMock(return_value=chunks())), patch.object(self.server,'generar_audio_bytes',AsyncMock(return_value=b'a')):
                    response=self.client.post('/chat/stream',json={'mensaje':'hola','session_id':self.sid,'mode':mode,'persona':persona},headers=self.headers)
                self.assertEqual(response.status_code,200,response.text)
                events=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
                self.assertEqual([e['type'] for e in events],['text','audio','done'])
                self.assertEqual(len({e['request_id'] for e in events}),1)
                self.assertEqual(events[0]['request_id'],response.headers['X-Operation-ID'])


class AsyncConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_distinct_http_sessions_generate_simultaneously_without_history_mixing(self):
        server=load_server(real_session_auth=True)
        both,release=asyncio.Event(),asyncio.Event()
        seen=[]
        async def provider(history,rag,question,**kwargs):
            seen.append(question)
            if len(seen)==2: both.set()
            await release.wait()
            return AssistantReply(assistant_text='Respuesta a '+question)
        transport=httpx.ASGITransport(app=server.app,raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport,base_url='http://test') as client:
            sessions=[(await client.post('/api/session',json={})).json() for _ in range(2)]
            with patch.object(server,'generar_respuesta_llm',provider),patch.object(server,'generar_audio_bytes',AsyncMock(return_value=b'a')):
                tasks=[asyncio.create_task(client.post('/chat',json={'mensaje':f'consulta{index}','session_id':session['session_id']},
                    headers={'X-Session-Token':session['session_token']})) for index,session in enumerate(sessions)]
                await asyncio.wait_for(both.wait(),3)
                release.set()
                results=await asyncio.gather(*tasks)
            self.assertEqual([response.status_code for response in results],[200,200])
            for index,session in enumerate(sessions):
                history=server.session_manager.repository.snapshot(session['session_id'])['history']
                self.assertEqual(history[0]['content'],f'consulta{index}')
                self.assertEqual(history[1]['content'],f'Respuesta a consulta{index}')

    async def test_json_disconnect_cancels_provider_and_releases_claim(self):
        server=load_server(real_session_auth=True)
        session=await server.session_manager.bootstrap()
        entered,closed=asyncio.Event(),asyncio.Event()
        messages=asyncio.Queue()
        body=json.dumps({'mensaje':'Hola','session_id':session['session_id']}).encode()
        await messages.put({'type':'http.request','body':body,'more_body':False})
        scope={'type':'http','asgi':{'version':'3.0','spec_version':'2.0'},'http_version':'1.1',
            'method':'POST','scheme':'http','path':'/chat','raw_path':b'/chat','query_string':b'',
            'root_path':'','client':('127.0.0.1',1),'server':('test',80),
            'headers':[(b'content-type',b'application/json'),(b'x-session-token',session['session_token'].encode())]}
        async def provider(*args,**kwargs):
            entered.set()
            try: await asyncio.Event().wait()
            finally: closed.set()
        async def send(message): pass
        with patch.object(server,'generar_respuesta_llm',provider):
            task=asyncio.create_task(server.app(scope,messages.get,send))
            await asyncio.wait_for(entered.wait(),3)
            await messages.put({'type':'http.disconnect'})
            with self.assertRaises(asyncio.CancelledError): await asyncio.wait_for(task,3)
        self.assertTrue(closed.is_set())
        state=server.session_manager.repository.snapshot(session['session_id'])
        self.assertIsNone(state['active_request_id'])
        self.assertEqual(state['history'],[])

    async def test_asgi_disconnect_cleans_stream_under_starlette_cancel_scope(self):
        server=load_server(real_session_auth=True)
        session=await server.session_manager.bootstrap()
        first_text,closed=asyncio.Event(),asyncio.Event()
        messages=asyncio.Queue()
        body=json.dumps({'mensaje':'Hola','session_id':session['session_id']}).encode()
        await messages.put({'type':'http.request','body':body,'more_body':False})
        scope={'type':'http','asgi':{'version':'3.0','spec_version':'2.0'},'http_version':'1.1',
            'method':'POST','scheme':'http','path':'/chat/stream','raw_path':b'/chat/stream',
            'query_string':b'','root_path':'','client':('127.0.0.1',1),'server':('test',80),
            'headers':[(b'content-type',b'application/json'),(b'x-session-token',session['session_token'].encode())]}
        async def send(message):
            if message['type']=='http.response.body' and b'"type": "text"' in message.get('body',b''):
                first_text.set()
        async def chunks():
            try:
                yield types.SimpleNamespace(choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content='Primera oración. Otra oración.',tool_calls=None))])
                await asyncio.Event().wait()
            finally: closed.set()
        with patch.object(server,'stream_respuesta_llm',AsyncMock(return_value=chunks())),patch.object(server,'generar_audio_bytes',AsyncMock(return_value=b'a')):
            task=asyncio.create_task(server.app(scope,messages.get,send))
            await asyncio.wait_for(first_text.wait(),3)
            await messages.put({'type':'http.disconnect'})
            await asyncio.wait_for(task,3)
        self.assertTrue(closed.is_set())
        state=server.session_manager.repository.snapshot(session['session_id'])
        self.assertIsNone(state['active_request_id'])
        self.assertEqual(state['history'],[])

    async def test_cancel_pending_tts_cleans_stream_and_history(self):
        server = load_server(real_session_auth=True)
        session = await server.session_manager.bootstrap()
        request = types.SimpleNamespace(headers={'X-Session-Token':session['session_token']})
        from security.inputs import ChatInput
        entered, stopped = asyncio.Event(), asyncio.Event()
        async def tts(*args):
            entered.set()
            try: await asyncio.Event().wait()
            finally: stopped.set()
        async def chunks():
            yield types.SimpleNamespace(choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content='Información institucional.',tool_calls=None))])
        events=[]
        with patch.object(server,'stream_respuesta_llm',AsyncMock(return_value=chunks())),patch.object(server,'generar_audio_bytes',tts):
            response=await server.responder_streaming(ChatInput(mensaje='Hola',session_id=session['session_id']),request)
            async def consume():
                async for event in response.body_iterator: events.append(event)
            task=asyncio.create_task(consume())
            await asyncio.wait_for(entered.wait(),3)
            await server.session_manager.cancel(session['session_id'])
            with self.assertRaises(asyncio.CancelledError): await asyncio.wait_for(task,3)
        self.assertTrue(stopped.is_set())
        self.assertEqual(len(events),1)
        self.assertEqual(server.session_manager.repository.snapshot(session['session_id'])['history'],[])

    async def test_http_busy_other_session_and_cancelled_provider(self):
        server=load_server(real_session_auth=True)
        entered,stopped=asyncio.Event(),asyncio.Event()
        async def blocked(*args,**kwargs):
            entered.set()
            try: await asyncio.Event().wait()
            finally: stopped.set()
        transport=httpx.ASGITransport(app=server.app,raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport,base_url='http://test') as client:
            first=(await client.post('/api/session',json={})).json()
            second=(await client.post('/api/session',json={})).json()
            headers={'X-Session-Token':first['session_token']}
            body={'mensaje':'Hola','session_id':first['session_id']}
            with patch.object(server,'generar_respuesta_llm',blocked):
                task=asyncio.create_task(client.post('/chat',json=body,headers=headers))
                await asyncio.wait_for(entered.wait(),3)
                busy=await client.post('/chat/stream',json=body,headers=headers)
                self.assertEqual(busy.status_code,409)
                other=await client.post('/chat',json={'mensaje':'','session_id':second['session_id']},headers={'X-Session-Token':second['session_token']})
                self.assertEqual(other.status_code,200)
                rid=server.session_manager.repository.snapshot(first['session_id'])['active_request_id']
                cancelled=await client.post('/api/session/cancel',json={'session_id':first['session_id'],'active_request_id':rid},headers=headers)
                self.assertEqual(cancelled.status_code,200)
                await asyncio.wait_for(stopped.wait(),3)
                try: await task
                except asyncio.CancelledError: pass
            state=server.session_manager.repository.snapshot(first['session_id'])
            self.assertIsNone(state['active_request_id'])
            self.assertEqual(state['history'],[])

    async def test_cancelled_sse_closes_provider_and_suppresses_actions(self):
        server=load_server(real_session_auth=True)
        session=await server.session_manager.bootstrap()
        request=types.SimpleNamespace(headers={'X-Session-Token':session['session_token']})
        from security.inputs import ChatInput
        closed=asyncio.Event()
        async def chunks():
            try:
                yield types.SimpleNamespace(choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content='Primera oración. Otra oración.',tool_calls=None))])
                await asyncio.Event().wait()
            finally: closed.set()
        with patch.object(server,'stream_respuesta_llm',AsyncMock(return_value=chunks())), patch.object(server,'generar_audio_bytes',AsyncMock(return_value=b'a')):
            response=await server.responder_streaming(ChatInput(mensaje='muéstrame fotos',session_id=session['session_id']),request)
            events=[]
            ready=asyncio.Event()
            async def consume():
                async for event in response.body_iterator:
                    events.append(event)
                    if len(events)==2: ready.set()
            task=asyncio.create_task(consume())
            await asyncio.wait_for(ready.wait(),3)
            await server.session_manager.cancel(session['session_id'])
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task,3)
        self.assertTrue(closed.is_set())
        self.assertNotIn('ui_action',''.join(events))
        state=server.session_manager.repository.snapshot(session['session_id'])
        self.assertEqual(state['history'],[])
        self.assertIsNone(state['active_request_id'])


if __name__=='__main__': unittest.main()
