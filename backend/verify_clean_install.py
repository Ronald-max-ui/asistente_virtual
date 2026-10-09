"""Isolated reproducible installation, real local index and HTTP readiness.
Provisioning copies the approved ONNX/VRM artifacts, never operational databases.
No production data is changed. Python 3.14 + Node 22.12+ required.
"""
import argparse,json,os,shutil,subprocess,sys,tempfile,time,urllib.request,socket
from pathlib import Path
BASE=Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--lock-output',type=Path,help='Write the validated clean dependency lock')
    args=parser.parse_args();report={'passed':False,'steps':[]}
    with tempfile.TemporaryDirectory(prefix='lia-clean-') as folder:
        root=Path(folder);backend=root/'backend';front=root/'avatar-kiosk'
        shutil.copytree(BASE,backend,ignore=shutil.ignore_patterns('venv','storage','chroma_db','.env','__pycache__','*.log','*.pyc','static'))
        shutil.copytree(BASE.parent/'avatar-kiosk',front,ignore=shutil.ignore_patterns('node_modules','dist','.env','*.log'))
        (backend/'static/avatars').mkdir(parents=True)
        shutil.copy2(BASE/'static/avatars/lia_original.vrm',backend/'static/avatars/lia_original.vrm')
        shutil.copytree(BASE/'static/media',backend/'static/media')
        shutil.copytree(BASE/'static/admin',backend/'static/admin')
        shutil.copytree(BASE/'storage/embedding_models',backend/'storage/embedding_models')
        env=dict(os.environ,APP_ENV='development',GROQ_API_KEY='synthetic-clean-install',ADMIN_API_TOKEN='',
            COMMERCIAL_DB_PATH=str(backend/'storage/commercial.sqlite3'),RUNTIME_DATABASE_PATH=str(backend/'storage/runtime.sqlite3'),
            CHROMA_DB_PATH=str(backend/'storage/knowledge_index'),CHROMA_MODEL_CACHE=str(backend/'storage/embedding_models'),
            ALLOWED_ORIGINS='http://localhost:5173',KNOWLEDGE_PREWARM='true',PYTHONIOENCODING='utf-8')
        def run(name,command,cwd=backend):
            start=time.perf_counter();result=subprocess.run(command,cwd=cwd,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=900)
            report['steps'].append({'name':name,'exit_code':result.returncode,'duration_ms':round((time.perf_counter()-start)*1000)})
            print(name+': '+str(result.returncode),flush=True)
            if result.returncode:
                # Installation commands contain no credentials; keep only failure diagnostics.
                report['failure']=name # Never persist package-manager URLs or environment values.
                raise RuntimeError(name)
        try:
            run('create_venv',[sys.executable,'-m','venv',str(root/'venv')])
            python=root/'venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
            run('python_dependencies',[str(python),'-m','pip','install','-r',str(backend/'requirements.txt')])
            run('dependency_integrity',[str(python),'-m','pip','check'])
            if args.lock_output:
                lock=subprocess.run([str(python),'-m','pip','freeze'],env=env,check=True,stdout=subprocess.PIPE).stdout
                if b' @ ' in lock:raise RuntimeError('non_registry_dependency')
                args.lock_output.write_bytes(lock)
                report['locked_packages']=len(lock.splitlines())
            npm=shutil.which('npm.cmd' if os.name=='nt' else 'npm')
            run('npm_ci',[npm,'ci'],front)
            run('commercial_migration',[str(python),'-B','migrate_commercial.py','--skip-avatar-copy'])
            run('migration_idempotent',[str(python),'-B','migrate_commercial.py','--skip-avatar-copy'])
            run('validate_knowledge',[str(python),'-B','validate_knowledge.py'])
            run('build_real_index',[str(python),'-B','rebuild_knowledge.py','--build'])
            run('verify_index',[str(python),'-B','rebuild_knowledge.py','--check'])
            run('evaluate_index',[str(python),'-B','rebuild_knowledge.py','--evaluate'])
            run('frontend_build',[npm,'run','build'],front)
            run('personalization_validation',[str(python),'-B','-m','unittest','discover','-s','tests','-p','test_phase9c.py'])
            run('commercial_operations_validation',[str(python),'-B','-m','unittest','discover','-s','tests','-p','test_phase9d.py'])
            with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            log=root/'server.log'
            with log.open('wb') as output:
                process=subprocess.Popen([str(python),'-m','uvicorn','server:app','--host','127.0.0.1','--port',str(port),'--workers','1','--no-access-log'],cwd=backend,env=env,stdout=output,stderr=output)
                try:
                    for _ in range(150):
                        if process.poll() is not None:raise RuntimeError('backend_start')
                        try:
                            with urllib.request.urlopen(f'http://127.0.0.1:{port}/health/ready',timeout=2) as response:
                                ready=json.load(response)
                            if ready['status']=='ready':break
                        except Exception:time.sleep(.2)
                    else:raise RuntimeError('readiness')
                    report['readiness']=ready;report['passed']=True
                finally:process.terminate();process.wait(timeout=15)
        except Exception as exc:
            report.setdefault('failure',str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps({'passed':report['passed'],'steps':len(report['steps']),'failure':report.get('failure')}))
    return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
