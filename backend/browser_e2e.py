"""Real Chrome/UI/HTTP E2E, fake providers, temporary commercial/runtime DBs.
Does not fake browser speech APIs. Native microphone/autoplay need physical QA.
"""
import argparse,asyncio,json,os,secrets,shutil,socket,subprocess,sys,tempfile,time,urllib.request
from pathlib import Path
import websockets
BASE=Path(__file__).resolve().parent

def port():
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));return sock.getsockname()[1]

async def execute(output,rounds=1,mode='web',real_avatar=False,duration=0,production_build=False):
    report={'passed':False,'checks':[],'rounds':rounds,'mode':mode,'heap_samples':[]}
    back,front=port(),port()
    if production_build:front=back
    url=f'http://127.0.0.1:{front}'
    env=dict(os.environ,APP_ENV='development',ALLOWED_ORIGINS=url,KNOWLEDGE_PREWARM='false',VITE_API_URL=f'http://127.0.0.1:{back}',PYTHONIOENCODING='utf8',E2E_REAL_AVATAR='true' if real_avatar else 'false',E2E_ADMIN_API_TOKEN=secrets.token_urlsafe(32))
    owned=[]
    with tempfile.TemporaryDirectory(prefix='lia-e2e-browser-') as folder:
        profile=Path(folder)/'chrome';log=Path(folder)/'process.log'
        with log.open('wb') as sink:
            try:
                def launch(command,cwd):
                    destination=subprocess.DEVNULL if command[0].endswith('chrome.exe') else sink
                    child=subprocess.Popen(command,cwd=cwd,env=env,stdout=destination,stderr=destination);owned.append(child);return child
                if production_build:
                    env['E2E_DIST_PATH']=str(Path(folder)/'dist')
                    build=subprocess.run([shutil.which('node'),str(BASE.parent/'avatar-kiosk/node_modules/vite/bin/vite.js'),'build','--outDir',env['E2E_DIST_PATH']],cwd=BASE.parent/'avatar-kiosk',env=env,stdout=sink,stderr=sink,timeout=90)
                    if build.returncode:raise RuntimeError('production_build')
                launch([sys.executable,'-m','uvicorn','e2e_app:app','--app-dir',str(BASE/'tests'),'--host','127.0.0.1','--port',str(back),'--no-access-log'],BASE)
                # Running Vite directly keeps cleanup ownership exact (no npm child shell).
                if not production_build:launch([shutil.which('node'),str(BASE.parent/'avatar-kiosk/node_modules/vite/bin/vite.js'),'--host','127.0.0.1','--port',str(front),'--strictPort'],BASE.parent/'avatar-kiosk')
                for _ in range(150):
                    try:
                        urllib.request.urlopen(url,timeout=1).close();urllib.request.urlopen(f'http://127.0.0.1:{back}/health/live',timeout=1).close();break
                    except Exception:await asyncio.sleep(.2)
                else:raise RuntimeError('servers_not_ready')
                chrome=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
                launch([str(chrome),'--headless=new','--remote-debugging-port=0','--user-data-dir='+str(profile),'--no-first-run','--disable-extensions','--enable-unsafe-swiftshader','--window-size=1280,900','about:blank'],BASE)
                for _ in range(100):
                    if (profile/'DevToolsActivePort').exists():break
                    await asyncio.sleep(.1)
                debug=int((profile/'DevToolsActivePort').read_text().splitlines()[0])
                endpoint=json.load(urllib.request.urlopen(f'http://127.0.0.1:{debug}/json/version'))['webSocketDebuggerUrl']
                async with websockets.connect(endpoint,max_size=20000000) as ws:
                    serial=0;session=None
                    async def call(method,params=None):
                        nonlocal serial
                        serial+=1;request={'id':serial,'method':method,'params':params or {}}
                        if session:request['sessionId']=session
                        await ws.send(json.dumps(request))
                        while True:
                            response=json.loads(await ws.recv())
                            if response.get('id')==serial:
                                if response.get('error'):raise RuntimeError('cdp_'+method)
                                return response.get('result',{})
                    target=await call('Target.createTarget',{'url':'about:blank'})
                    session=(await call('Target.attachToTarget',{'targetId':target['targetId'],'flatten':True}))['sessionId']
                    await call('Page.enable');await call('Network.enable')
                    await call('Page.addScriptToEvaluateOnNewDocument',{'source':"window.__e2eAvatarReady=false;const originalLog=console.log.bind(console);console.log=(...args)=>{if(args.some(x=>String(x).includes('Modelo VRM cargado')))window.__e2eAvatarReady=true;originalLog(...args)}"})
                    async def evaluate(expression):
                        result=await call('Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True})
                        if result.get('exceptionDetails'):raise RuntimeError('browser_script_failed')
                        return result.get('result',{}).get('value')
                    async def until(expression,seconds=12):
                        started=time.monotonic()
                        while time.monotonic()-started<seconds:
                            if await evaluate(expression):return
                            await asyncio.sleep(.1)
                        report['failed_condition']=expression;
                        report['ui_state']=await evaluate("document.getElementById('status-badge')?.textContent");
                        report['dialogs']=await evaluate("[...document.querySelectorAll('.ov-backdrop')].map(x=>({id:x.id,visible:x.classList.contains('ov-visible')}))");
                        report['focused_control']=await evaluate("document.activeElement?.name||document.activeElement?.id");
                        raise RuntimeError('ui_condition_timeout')
                    async def click(selector):
                        box=await evaluate(f"(()=>{{const r=document.querySelector({json.dumps(selector)}).getBoundingClientRect();return {{x:r.x+r.width/2,y:r.y+r.height/2}}}})()")
                        await call('Input.dispatchMouseEvent',{'type':'mousePressed',**box,'button':'left','clickCount':1})
                        await call('Input.dispatchMouseEvent',{'type':'mouseReleased',**box,'button':'left','clickCount':1})
                    async def ask(text):
                        await until("!document.getElementById('text-send').disabled")
                        await evaluate(f"document.getElementById('text-message').value={json.dumps(text)}")
                        await click('#text-send')
                    def passed(name):report['checks'].append(name)
                    await call('Page.navigate',{'url':url+'/?mode='+mode})
                    await until("document.getElementById('text-send') && !document.getElementById('text-send').disabled")
                    passed('session_bootstrap_text_ready')
                    if real_avatar:
                        await until("window.__e2eAvatarReady",30)
                        passed('approved_avatar_loaded')
                    else:
                        await until("document.getElementById('capability-notice').textContent.includes('avatar')")
                        passed('failed_avatar_keeps_conversation')
                    if not await evaluate("fetch('/favicon.svg').then(r=>r.ok)"):raise RuntimeError('favicon_unavailable')
                    passed('favicon_available')
                    report['native_voice_available']=await evaluate('Boolean(window.SpeechRecognition||window.webkitSpeechRecognition)')
                    started=time.monotonic()
                    for index in range(10000 if duration else rounds):
                        if duration and time.monotonic()-started>=duration:break
                        await ask('Información de Turismo')
                        await until("document.getElementById('subtitles').textContent.includes('Turismo') && !document.getElementById('text-send').disabled")
                        if index==0:passed('text_audio_response')
                        await ask('Voy a cancelar esta consulta')
                        await until("!document.getElementById('stop-btn').hidden")
                        await click('#stop-btn');await until("!document.getElementById('text-send').disabled")
                        if index==0:passed('cancel_then_ready')
                        await ask('Información sin audio')
                        await until("document.getElementById('subtitles').textContent.includes('sin audio') && !document.getElementById('text-send').disabled")
                        if index==0:passed('tts_failure_text_continues')
                        await ask('Fallo proveedor')
                        await until("document.getElementById('subtitles').textContent.includes('Ocurrió un error') && !document.getElementById('text-send').disabled")
                        if index==0:passed('llm_failure_recovers')
                        if index%10==0:
                            report['heap_samples'].append({'round':index,'bytes':await evaluate('performance.memory?.usedJSHeapSize')})
                            output.parent.mkdir(parents=True,exist_ok=True)
                            output.write_text(json.dumps(report,indent=2),encoding='utf8')
                    async def web_operations():
                        await ask('Quiero dejar mis datos para Turismo')
                        await until("Boolean(document.querySelector('#lead-modal.ov-visible'))")
                        await until("document.activeElement?.name==='nombre'")
                        if not await evaluate("document.querySelector('#lead-modal [role=dialog]').getAttribute('aria-modal')==='true'"):raise RuntimeError('dialog_accessibility')
                        await evaluate("document.getElementById('lead-submit-btn').focus()")
                        await call('Input.dispatchKeyEvent',{'type':'keyDown','key':'Tab','code':'Tab','windowsVirtualKeyCode':9})
                        if not await evaluate("document.activeElement.classList.contains('ov-close')"):raise RuntimeError('focus_trap')
                        passed('accessible_lead_dialog')
                        await evaluate("document.querySelector('#lead-form [name=nombre]').value='Synthetic';document.querySelector('#lead-form [name=whatsapp]').value='999888777'")
                        await click('#lead-submit-btn')
                        await until("document.getElementById('lead-msg').textContent.includes('Listo')")
                        passed('lead_registered')
                        await call('Input.dispatchKeyEvent',{'type':'keyDown','key':'Escape','code':'Escape','windowsVirtualKeyCode':27})
                        await until("!document.querySelector('#lead-modal.ov-visible')")
                        passed('escape_closes_dialog')
                        await ask('Quiero pagar la inscripción de Turismo')
                        await until("Boolean(document.querySelector('#payment-modal.ov-visible'))")
                        if not await evaluate("document.querySelector('#payment-modal').textContent.includes('80')"):raise RuntimeError('catalog_price')
                        from PIL import Image
                        image=Path(folder)/'fixture.png';Image.new('RGB',(4,4),'white').save(image)
                        doc=await call('DOM.getDocument');node=await call('DOM.querySelector',{'nodeId':doc['root']['nodeId'],'selector':'#voucher-form input[type=file]'})
                        await call('DOM.setFileInputFiles',{'nodeId':node['nodeId'],'files':[str(image)]})
                        await click('#voucher-submit-btn')
                        await until("document.getElementById('payment-modal')._uploadBusy===true")
                        await call('Input.dispatchKeyEvent',{'type':'keyDown','key':'Escape','code':'Escape','windowsVirtualKeyCode':27})
                        if not await evaluate("document.querySelector('#payment-modal.ov-visible')!==null"):raise RuntimeError('busy_upload_closed')
                        passed('active_upload_blocks_escape')
                        await until("document.getElementById('voucher-msg').textContent.includes('pendiente de revisión')")
                        passed('voucher_pending_review')
                        if production_build:
                            await evaluate("fetch('/reset-session',{method:'POST',headers:{'Content-Type':'application/json','X-Session-Token':sessionStorage.getItem('av_kiosk_session_token'),'Idempotency-Key':crypto.randomUUID()},body:JSON.stringify({mensaje:'',session_id:sessionStorage.getItem('av_kiosk_session_id')})}).then(r=>{if(!r.ok) throw new Error('reset');document.getElementById('subtitles').textContent='';})")
                        else:await evaluate("import('/src/api/client.js').then(m=>m.resetConversation())")
                        await until("document.getElementById('subtitles').textContent===''")
                        passed('conversation_reset')
                    if mode=='web':await web_operations()
                    else:passed('kiosk_repeated_conversation')
                    report['elapsed_seconds']=round(time.monotonic()-started,3)
                    await call('Page.setWebLifecycleState',{'state':'frozen'})
                    await asyncio.sleep(.25)
                    await call('Page.setWebLifecycleState',{'state':'active'})
                    await until("!document.getElementById('text-send').disabled")
                    passed('browser_freeze_resume')
                    await call('Network.emulateNetworkConditions',{'offline':True,'latency':0,'downloadThroughput':0,'uploadThroughput':0})
                    await until("document.getElementById('status-badge').textContent.includes('Sin conexión')")
                    await call('Network.emulateNetworkConditions',{'offline':False,'latency':0,'downloadThroughput':-1,'uploadThroughput':-1})
                    await until("!document.getElementById('text-send').disabled")
                    passed('offline_online_controls_recover')
                    private_request=urllib.request.Request(f'http://127.0.0.1:{back}/api/admin/avatars/lia_original/activate',data=b'',method='POST',headers={'Authorization':'Bearer '+env['E2E_ADMIN_API_TOKEN']})
                    with urllib.request.urlopen(private_request) as changed:
                        if changed.status!=200:raise RuntimeError('avatar_selection')
                    await call('Page.reload')
                    await until("window.__e2eAvatarReady",30)
                    await until("!document.getElementById('text-send').disabled")
                    passed('avatar_change_reload')
                    if production_build:
                        if not await evaluate("fetch('/').then(r=>r.headers.get('Content-Security-Policy')?.includes(\"script-src 'self'\") && r.headers.get('Cache-Control')==='no-cache')"):raise RuntimeError('frontend_headers')
                        passed('production_build_csp')
                    await call('Emulation.setDeviceMetricsOverride',{'width':390,'height':844,'deviceScaleFactor':1,'mobile':True})
                    await asyncio.sleep(.2)
                    layout=await evaluate("(()=>{const c=document.getElementById('ui-container').getBoundingClientRect(),s=document.getElementById('subtitles').getBoundingClientRect();return {contained:c.left>=0&&c.right<=innerWidth,caption_above:s.bottom<=c.top}})()")
                    if not all(layout.values()):raise RuntimeError('responsive_controls')
                    report['responsive_layout']=layout;passed('narrow_viewport_layout')
                    report['passed']=True
                    try: await call('Browser.close')
                    except websockets.ConnectionClosed: pass
            except Exception as exc:report['failure']=str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__
            finally:
                for child in reversed(owned):
                    if child.poll() is None:child.terminate()
                for child in reversed(owned):
                    try:child.wait(timeout=15)
                    except subprocess.TimeoutExpired:child.kill();child.wait()
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report));return 0 if report['passed'] else 1

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--rounds',type=int,default=1)
    parser.add_argument('--mode',choices=('web','kiosk'),default='web')
    parser.add_argument('--production-build',action='store_true')
    parser.add_argument('--real-avatar',action='store_true')
    parser.add_argument('--duration-seconds',type=int,default=0)
    args=parser.parse_args()
    if not 0<=args.duration_seconds<=86400:parser.error('duration outside limits')
    if not 1<=args.rounds<=10000:parser.error('rounds outside limits')
    return asyncio.run(execute(args.output,args.rounds,args.mode,args.real_avatar,args.duration_seconds,args.production_build))
if __name__=='__main__':raise SystemExit(main())
