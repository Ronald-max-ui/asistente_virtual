"""Abrupt process restart with private temporary DBs and synthetic providers."""
import argparse,io,json,os,queue,socket,subprocess,sys,tempfile,threading,time
from pathlib import Path
import httpx
from PIL import Image
BASE=Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    report={'passed':False,'checks':[]};process=None
    with tempfile.TemporaryDirectory(prefix='lia-restart-') as folder:
        root=Path(folder)
        from persistence.sqlite_repository import SQLiteRepository
        from migrate_commercial import migrate,seed_configuration
        repository=SQLiteRepository(root/'commercial.sqlite3');migration=migrate(repository)
        if migration['rejected']:raise RuntimeError('Invalid fixture')
        seed_configuration(repository)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        url=f'http://127.0.0.1:{port}'
        env=dict(os.environ,LIA_RESTART_WORKSPACE=str(root),APP_ENV='development',GROQ_API_KEY='synthetic-restart-provider',ADMIN_API_TOKEN='',
            COMMERCIAL_DB_PATH=str(root/'commercial.sqlite3'),RUNTIME_DATABASE_PATH=str(root/'runtime.sqlite3'),KNOWLEDGE_PREWARM='false',ALLOWED_ORIGINS='http://localhost:5173',PYTHONIOENCODING='utf8')
        with (root/'process.log').open('wb') as log:
            def start():
                child=subprocess.Popen([sys.executable,'-m','uvicorn','restart_app:app','--app-dir',str(BASE/'tests'),'--host','127.0.0.1','--port',str(port),'--no-access-log'],cwd=BASE,env=env,stdout=log,stderr=log)
                for _ in range(100):
                    try:
                        ready=httpx.get(url+'/health/ready',timeout=1)
                        if ready.status_code==200:return child
                    except Exception:pass
                    if child.poll() is not None:raise RuntimeError('Startup failed')
                    time.sleep(.1)
                child.terminate();child.wait();raise RuntimeError('Readiness timeout')
            def require(value,name):
                if not value:raise RuntimeError(name)
                report['checks'].append(name)
            try:
                process=start();identity=httpx.post(url+'/api/session',json={}).json();sid=identity['session_id'];headers={'X-Session-Token':identity['session_token']}
                body={'mensaje':'Información de Turismo','session_id':sid}
                require(httpx.post(url+'/chat',json=body,headers=headers).status_code==200,'completed_turn')
                lead=httpx.post(url+'/api/leads',data={'session_id':sid,'nombre':'Synthetic','whatsapp':'999888777','carrera':'turismo'},headers={**headers,'Idempotency-Key':'restart-lead'})
                require(lead.status_code==200,'lead_created')
                image=io.BytesIO();Image.new('RGB',(4,4),'white').save(image,format='PNG')
                voucher=httpx.post(url+'/api/vouchers',data={'session_id':sid,'carrera':'turismo','concepto':'inscripcion','monto':'80'},headers={**headers,'Idempotency-Key':'restart-voucher'},files={'imagen':('fixture.png',image.getvalue(),'image/png')})
                require(voucher.status_code==200,'voucher_created')
                original_config=httpx.get(url+'/api/config').json();started=queue.Queue()
                def inflight():
                    try:
                        with httpx.stream('POST',url+'/chat/stream',json=body,headers=headers,timeout=70) as response:
                            notified=False
                            for line in response.iter_lines():
                                if not notified and line.startswith('data: '):started.put(True);notified=True
                    except Exception:pass
                thread=threading.Thread(target=inflight,daemon=True);thread.start();started.get(timeout=10)
                process.terminate();process.wait(timeout=15);thread.join(timeout=5)
                process=start()
                require(httpx.post(url+'/api/session',json={'session_id':sid},headers=headers).status_code==200,'session_credential_recovered')
                require(httpx.get(url+'/api/config').json()==original_config,'commercial_avatar_config_recovered')
                require(httpx.get(url+'/health/ready').json()['knowledge']['status']=='ready','index_ready_after_restart')
                from persistence.sqlite_runtime_repository import SQLiteRuntimeRepository
                runtime=SQLiteRuntimeRepository(root/'runtime.sqlite3');snapshot=runtime.snapshot(sid)
                require(len(snapshot['history'])==2,'incomplete_turn_not_committed')
                require(snapshot['active_request_id'] is not None,'orphan_lease_visible')
                require(httpx.post(url+'/chat',json={**body,'replace_active':True},headers=headers).status_code==200,'explicit_replace_recovers_orphan')
                require(runtime.snapshot(sid)['lead_id']==lead.json()['lead_id'],'lead_association_recovered')
                retry=httpx.post(url+'/api/leads',data={'session_id':sid,'nombre':'Synthetic','whatsapp':'999888777','carrera':'turismo'},headers={**headers,'Idempotency-Key':'restart-lead'})
                require(retry.json()==lead.json(),'lead_retry_idempotent_after_restart')
                retry=httpx.post(url+'/api/vouchers',data={'session_id':sid,'carrera':'turismo','concepto':'inscripcion','monto':'80'},headers={**headers,'Idempotency-Key':'restart-voucher'},files={'imagen':('fixture.png',image.getvalue(),'image/png')})
                require(retry.json()==voucher.json(),'voucher_retry_idempotent_after_restart')
                saved=runtime.get_record('vouchers',voucher.json()['voucher_id'])
                require(saved['lead_id']==lead.json()['lead_id'] and saved['status']=='pending_review','voucher_association_status_recovered')
                require((root/'vouchers'/saved['file_reference']).is_file(),'voucher_image_recovered')
                require(httpx.post(url+'/reset-session',json={'mensaje':'','session_id':sid},headers=headers).status_code==200,'reset_after_restart')
                require(runtime.snapshot(sid)['history']==[] and runtime.snapshot(sid)['lead_id']==lead.json()['lead_id'] and runtime.get_record('vouchers',voucher.json()['voucher_id']) is not None,'reset_preserves_commercial_data')
                report['passed']=True
            except Exception as exc:report['failure']=str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__
            finally:
                if process and process.poll() is None:process.terminate();process.wait(timeout=15)
    args.output.write_text(json.dumps(report,indent=2),encoding='utf8');print(json.dumps(report));return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
