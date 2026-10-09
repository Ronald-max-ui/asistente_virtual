"""Real Chrome login/cookie/CSRF/RBAC E2E; all database writes are temporary."""
import argparse,asyncio,base64,json,os,secrets,socket,subprocess,sys,tempfile,time,urllib.request
from pathlib import Path
import websockets
BASE=Path(__file__).resolve().parent
async def execute(output):
    report={'passed':False,'checks':[]};owned=[]
    with tempfile.TemporaryDirectory(prefix='lia-admin-e2e-') as folder:
        root=Path(folder)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        url=f'http://127.0.0.1:{port}'
        password='Synthetic!'+secrets.token_urlsafe(24)
        env=dict(os.environ,APP_ENV='development',ALLOWED_ORIGINS=url,ADMIN_COOKIE_SECURE='false',ADMIN_LEGACY_TOKEN_ENABLED='false',E2E_ADMIN_PASSWORD=password,KNOWLEDGE_PREWARM='false',PYTHONIOENCODING='utf8',E2E_DIST_PATH=str(root/'dist'),VITE_API_URL=url)
        with (root/'process.log').open('wb') as log:
            try:
                def launch(args):
                    destination=subprocess.DEVNULL if args[0].endswith('chrome.exe') else log
                    process=subprocess.Popen(args,cwd=BASE,env=env,stdout=destination,stderr=destination);owned.append(process)
                build=subprocess.run(['node',str(BASE.parent/'avatar-kiosk/node_modules/vite/bin/vite.js'),'build','--outDir',env['E2E_DIST_PATH']],cwd=BASE.parent/'avatar-kiosk',env=env,stdout=log,stderr=log,timeout=90)
                if build.returncode:raise RuntimeError('production_build')
                launch([sys.executable,'-m','uvicorn','admin_e2e_app:app','--app-dir',str(BASE/'tests'),'--host','127.0.0.1','--port',str(port),'--no-access-log'])
                for _ in range(150):
                    try:urllib.request.urlopen(url+'/health/live',timeout=1).close();break
                    except Exception:await asyncio.sleep(.2)
                else:raise RuntimeError('startup_failed')
                profile=root/'chrome'
                launch(['C:/Program Files/Google/Chrome/Application/chrome.exe','--headless=new','--remote-debugging-port=0','--user-data-dir='+str(profile),'--no-first-run','--disable-extensions','about:blank'])
                for _ in range(100):
                    if (profile/'DevToolsActivePort').exists():break
                    await asyncio.sleep(.1)
                debug=int((profile/'DevToolsActivePort').read_text().splitlines()[0])
                endpoint=json.load(urllib.request.urlopen(f'http://127.0.0.1:{debug}/json/version'))['webSocketDebuggerUrl']
                async with websockets.connect(endpoint,max_size=2000000) as ws:
                    serial=0;session=None
                    async def call(method,params=None):
                        nonlocal serial
                        serial+=1;command={'id':serial,'method':method,'params':params or {}}
                        if session:command['sessionId']=session
                        await ws.send(json.dumps(command))
                        while True:
                            response=json.loads(await ws.recv())
                            if response.get('id')==serial:
                                if 'error' in response:raise RuntimeError('browser_protocol')
                                return response.get('result',{})
                    target=await call('Target.createTarget',{'url':'about:blank'})
                    session=(await call('Target.attachToTarget',{'targetId':target['targetId'],'flatten':True}))['sessionId']
                    await call('Page.enable');await call('Network.enable')
                    async def evaluate(expression):
                        result=await call('Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True,'userGesture':True})
                        if result.get('exceptionDetails'):raise RuntimeError('browser_script')
                        return result.get('result',{}).get('value')
                    async def until(expression):
                        for _ in range(100):
                            if await evaluate(expression):return
                            await asyncio.sleep(.1)
                        report['diagnostic']=await evaluate("({ready:document.readyState,status:document.querySelector('#status')?.textContent,loginHidden:document.querySelector('#login')?.hidden,sessionHidden:document.querySelector('#session')?.hidden,title:document.title})")
                        raise RuntimeError('browser_condition')
                    def check(name,value):
                        if not value:
                            report['failed_check']=name
                            raise RuntimeError(name)
                        report['checks'].append(name)
                    await call('Page.navigate',{'url':url+'/admin/'})
                    await until("document.querySelector('#status')?.textContent.includes('Inicia sesión')")
                    async def login(username):
                        await evaluate("document.querySelector('#username').value="+json.dumps(username)+";document.querySelector('#password').value="+json.dumps(password)+";document.querySelector('#login').requestSubmit()")
                        await until("!document.querySelector('#session').hidden && !document.querySelector('#logout').disabled")
                    await login('synthetic_admin')
                    await call('Emulation.setDeviceMetricsOverride',{'width':1365,'height':900,'deviceScaleFactor':1,'mobile':False})
                    check('login_ui',True)
                    check('me_superadmin',await evaluate("(async()=> (await (await fetch('/api/admin/auth/me')).json()).role === 'superadmin')()"))
                    cookies=await call('Network.getCookies',{'urls':[url+'/api/admin/auth/me']})
                    check('cookie_httponly',any(c['httpOnly'] and c['sameSite']=='Strict' for c in cookies['cookies']))
                    check('cookie_inaccessible_js',await evaluate("!document.cookie.includes('lia_admin_session')"))
                    check('csrf_missing_rejected',await evaluate("(async()=> (await fetch('/api/admin/auth/logout',{method:'POST'})).status===403)()"))
                    check('read_modify_audit',await evaluate("(async()=>{const programs=await(await fetch('/api/admin/programs')).json();const p=programs[0];for(const k of ['created_at','updated_at','created_by','updated_by'])delete p[k];p.name+=' browser test';const csrf=(await(await fetch('/api/admin/auth/csrf')).json()).csrf_token;const response=await fetch('/api/admin/programs/'+p.id,{method:'PUT',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(p)});const audit=await(await fetch('/api/admin/audit')).json();return response.status===200 && audit.some(a=>a.resource_id===p.id && a.after.name===p.name)})()"))
                    async def screen(module):
                        await evaluate("document.querySelector('[data-module="+module+"]')?.click()")
                        await until("document.querySelector('#content h1') && document.querySelector('#content').firstElementChild.getAttribute('aria-busy')==='false'")
                    async def fill(name,value):
                        await evaluate("(()=>{const input=document.querySelector('dialog [name="+name+"]');input.value="+json.dumps(value)+";input.dispatchEvent(new Event('change',{bubbles:true}));input.dispatchEvent(new Event('input',{bubbles:true}));})()")
                    async def save_editor(confirm=False):
                        await evaluate("[...document.querySelectorAll('dialog')].at(-1).querySelector('form').requestSubmit()")
                        if confirm:
                            await until("document.querySelectorAll('dialog').length===2")
                            await evaluate("document.querySelectorAll('dialog')[1].querySelector('form').requestSubmit()")
                        await until("document.querySelectorAll('dialog').length===0")
                    await until("document.querySelector('#content').textContent.includes('Estado de Lía')")
                    output.parent.mkdir(parents=True,exist_ok=True)
                    image=await call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})
                    (output.parent/'fase-9d-dashboard.png').write_bytes(base64.b64decode(image['data']))
                    check('dashboard_real_cards',await evaluate("document.querySelector('#content').textContent.includes('Programas activos')"))
                    await screen('programs')
                    await evaluate("[...document.querySelectorAll('#content tbody tr')].find(r=>r.textContent.includes('Turismo')).querySelector('button').click()")
                    await until("!!document.querySelector('dialog [name=name]')")
                    check('immutable_program_id',await evaluate("document.querySelector('dialog [name=id]').disabled"))
                    await fill('name','Turismo browser fixture');await save_editor()
                    check('edit_program_ui',await evaluate("document.querySelector('#content').textContent.includes('Turismo browser fixture')"))
                    await screen('prices')
                    await evaluate("for(const [name,value] of [['program','turismo'],['concept','inscripcion']]){const e=document.querySelector('#content [name='+name+']');e.value=value;e.dispatchEvent(new Event('change',{bubbles:true}));}document.querySelector('#content tbody button').click()")
                    await until("!!document.querySelector('dialog [name=amount]')")
                    await fill('amount','120.50');await save_editor(True)
                    check('price_decimal_confirmation_ui',await evaluate("document.querySelector('#content').textContent.includes('S/ 120.50')"))
                    async def public_price(expected):
                        return await evaluate("(async()=>{const s=await(await fetch('/api/session',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})).json();const r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json','X-Session-Token':s.session_token},body:JSON.stringify({session_id:s.session_id,mensaje:'¿Cuánto cuesta la inscripción de Turismo?',mode:'web',persona:'sales'})});const result=await r.json();return r.status===200 && result.texto.toLowerCase().includes("+json.dumps(expected)+")})()")
                    check('panel_price_public_chat_no_rebuild',await public_price('120.5'))
                    async def price_row(concept):
                        await screen('prices')
                        await evaluate("for(const [name,value] of [['program','turismo'],['concept',"+json.dumps(concept)+"]]){const e=document.querySelector('#content [name='+name+']');e.value=value;e.dispatchEvent(new Event('change',{bubbles:true}));}")
                    await price_row('matricula')
                    check('pending_not_displayed_zero',await evaluate("document.querySelector('#content tbody tr').textContent.includes('Pendiente') && !document.querySelector('#content tbody tr').textContent.includes('S/ 0.00')"))
                    await evaluate("document.querySelector('#content tbody button').click()")
                    await until("!!document.querySelector('dialog [name=amount]')")
                    check('dialog_accessible',await evaluate("document.querySelector('dialog').getAttribute('aria-modal')==='true' && document.querySelector('dialog').contains(document.activeElement)"))
                    await evaluate("const controls=[...document.querySelector('dialog').querySelectorAll('input:not(:disabled),select:not(:disabled),textarea,button')];controls.at(-1).focus()")
                    await call('Input.dispatchKeyEvent',{'type':'keyDown','key':'Tab','code':'Tab','windowsVirtualKeyCode':9})
                    await call('Input.dispatchKeyEvent',{'type':'keyUp','key':'Tab','code':'Tab','windowsVirtualKeyCode':9})
                    check('dialog_focus_trap',await evaluate("document.querySelector('dialog').contains(document.activeElement)"))
                    await fill('status','free');check('free_amount_zero_disabled',await evaluate("document.querySelector('dialog [name=amount]').value==='0' && document.querySelector('dialog [name=amount]').disabled"));await save_editor(True)
                    await price_row('matricula');check('free_display_confirmed',await evaluate("document.querySelector('#content tbody tr').textContent.includes('Gratis') && document.querySelector('#content tbody tr').textContent.includes('S/ 0.00')"))
                    await evaluate("document.querySelector('#content tbody button').click()")
                    await until("!!document.querySelector('dialog [name=amount]')");await fill('status','pending');await save_editor(True)
                    check('pending_saved_null',await evaluate("(async()=> (await(await fetch('/api/admin/prices')).json()).find(p=>p.program==='turismo' && p.concept==='matricula' && !p.campaign_id).amount===null)()"))
                    await screen('campaigns');await evaluate("[...document.querySelectorAll('#content button')].find(b=>b.textContent==='Nueva campaña').click()")
                    await until("!!document.querySelector('dialog [name=name]')")
                    await fill('name','Synthetic browser campaign');await fill('program','turismo')
                    await until("document.querySelector('dialog').textContent.includes('Precio base actual: S/ 120.50')")
                    await save_editor(True)
                    check('campaign_ui_atomic',await evaluate("document.querySelector('#content').textContent.includes('Synthetic browser campaign') && document.querySelector('#content').textContent.includes('Gratis')"))
                    check('panel_campaign_public_chat_no_rebuild',await public_price('gratuit'))
                    await evaluate("[...document.querySelectorAll('#content button')].find(b=>b.textContent==='Nueva campaña').click()")
                    await until("!!document.querySelector('dialog [name=name]')");await fill('name','Synthetic overlapping campaign');await fill('program','turismo')
                    await until("document.querySelector('dialog').textContent.includes('Precio base actual: S/ 120.50')")
                    await evaluate("document.querySelector('dialog form').requestSubmit()")
                    await until("document.querySelectorAll('dialog').length===2")
                    await evaluate("document.querySelectorAll('dialog')[1].querySelector('form').requestSubmit()")
                    await until("document.querySelector('dialog .error-box')?.textContent.includes('combinación')")
                    check('overlap_clear_ui',True)
                    await evaluate("[...document.querySelectorAll('dialog button')].find(b=>b.textContent==='Cerrar').click()")
                    await screen('avatars');await evaluate("[...document.querySelectorAll('#content button')].find(b=>b.textContent==='Usar este avatar').click()")
                    await until("document.querySelector('#status').textContent==='Listo.'")
                    check('avatar_public_config',await evaluate("(async()=> (await(await fetch('/api/config')).json()).avatar.id==='lia_original')()"))
                    await screen('appearance');check('appearance_existing_settings',await evaluate("!!document.querySelector('#content [name=kiosk_text_enabled]')"))
                    check('personalization_sections',await evaluate("['Identidad','Asistente','Kiosk','Vista previa'].every(t=>[...document.querySelectorAll('#content h2')].some(h=>h.textContent===t))"))
                    old_etag=await evaluate("(async()=> (await fetch('/api/config')).headers.get('ETag'))()")
                    from PIL import Image
                    logo=root/'institution.png';Image.new('RGB',(32,32),'navy').save(logo)
                    await call('DOM.enable');document_node=(await call('DOM.getDocument'))['root']['nodeId']
                    file_node=(await call('DOM.querySelector',{'nodeId':document_node,'selector':'[name=logo_file]'}))['nodeId']
                    await call('DOM.setFileInputFiles',{'nodeId':file_node,'files':[str(logo)]})
                    await evaluate("[...document.querySelectorAll('#content button')].find(b=>b.textContent==='Subir logo').click()")
                    await until("document.querySelector('#content [name=logo_url]').value.startsWith('/static/branding/') && !document.querySelector('#content button[type=submit]').disabled")
                    check('logo_upload_validated_ui',True)
                    document_node=(await call('DOM.getDocument'))['root']['nodeId']
                    file_node=(await call('DOM.querySelector',{'nodeId':document_node,'selector':'[name=favicon_file]'}))['nodeId']
                    await call('DOM.setFileInputFiles',{'nodeId':file_node,'files':[str(logo)]})
                    await evaluate("[...document.querySelectorAll('#content button')].find(b=>b.textContent==='Subir favicon').click()")
                    await until("document.querySelector('#content [name=favicon_url]').value.startsWith('/static/branding/') && !document.querySelector('#content button[type=submit]').disabled")
                    await evaluate("for(const [name,value] of [['assistant_name','Instituto Demo'],['primary_color','#135790'],['initial_message','Bienvenido al instituto.'],['voice_id','es-PE-AlexNeural']]){const input=document.querySelector('#content [name='+name+']');input.value=value;input.dispatchEvent(new Event('input',{bubbles:true}));}document.querySelector('#content form').requestSubmit()")
                    await until("document.querySelector('#content .brand-preview')?.textContent.includes('Instituto Demo') && !document.querySelector('#content button[type=submit]').disabled")
                    check('branding_saved_dynamic_config',await evaluate("(async()=>{const c=await(await fetch('/api/config')).json();return c.assistant.name==='Instituto Demo' && c.assistant.primary_color==='#135790' && c.assistant.logo_url.includes('/static/branding/') && c.voice.voice_id==='es-PE-AlexNeural'})()"))
                    check('personalization_etag_changed',(await evaluate("(async()=> (await fetch('/api/config')).headers.get('ETag'))()"))!=old_etag)
                    await evaluate("[...document.querySelectorAll('#content button')].find(b=>b.textContent==='Probar voz').click()")
                    await until("document.querySelector('#content audio')?.src.startsWith('blob:')")
                    check('voice_preview_fixed_audio_ui',True)
                    image=await call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})
                    (output.parent/'fase-9d-appearance.png').write_bytes(base64.b64decode(image['data']))
                    await call('Page.navigate',{'url':url+'/'})
                    await until("document.title==='Instituto Demo' && document.querySelector('#assistant-logo')?.complete && document.querySelector('#text-form')?.hidden===false")
                    check('public_reload_name_color_logo_favicon_no_build',await evaluate("document.querySelector('#assistant-name').textContent==='Instituto Demo' && document.querySelector('#assistant-logo').naturalWidth===32 && document.documentElement.style.getPropertyValue('--assistant-primary')==='#135790' && document.querySelector('#app-favicon').href.includes('/static/branding/')"))
                    check('initial_message_visible_plain',await evaluate("document.querySelector('#subtitles').textContent==='Bienvenido al instituto.'"))
                    await evaluate("document.querySelector('#text-message').value='Consulta de voz';document.querySelector('#text-form').requestSubmit()")
                    await until("document.querySelector('#subtitles').textContent.includes('Turismo') && !document.querySelector('#text-send').disabled")
                    check('voice_new_conversation_selected',await evaluate("(async()=> (await(await fetch('/api/admin/test/voice-observed')).json()).voice_id==='es-PE-AlexNeural')()"))
                    await call('Page.navigate',{'url':url+'/admin/'})
                    await until("!document.querySelector('#session')?.hidden && !document.querySelector('#logout').disabled")
                    await screen('leads');check('lead_paged_ui',await evaluate("document.querySelector('#content').textContent.includes('Synthetic prospect') && document.querySelector('#content').textContent.includes('Página 1')"))
                    check('commercial_public_capture',await evaluate("(async()=>{const session=await(await fetch('/api/session',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})).json();const form=new FormData();for(const [key,value] of Object.entries({nombre:'Synthetic commercial follow-up',whatsapp:'999333666',carrera:'Contabilidad',session_id:session.session_id,origen:'web'}))form.append(key,value);const r=await fetch('/api/leads',{method:'POST',headers:{'X-Session-Token':session.session_token,'Idempotency-Key':crypto.randomUUID()},body:form});const result=await r.json();window.__commercialFixture={session,lead_id:result.lead_id};return r.ok})()"))
                    await screen('leads');await until("document.querySelector('#content').textContent.includes('Synthetic commercial follow-up')")
                    async def open_commercial():
                        await evaluate("[...document.querySelectorAll('.lead-cards article')].find(c=>c.textContent.includes('Synthetic commercial follow-up')).querySelector('button').click()")
                        await until("!!document.querySelector('dialog .lead-profile')")
                    async def action(label):
                        await open_commercial();await evaluate("[...document.querySelectorAll('dialog button')].find(b=>b.textContent==="+json.dumps(label)+").click()")
                    await action('Estado y responsable');await until("!!document.querySelector('dialog [name=status]')")
                    await fill('status','contacted')
                    actor=await evaluate("(async()=> (await(await fetch('/api/admin/auth/me')).json()).id)()")
                    await fill('assigned_to_user_id',actor);await save_editor()
                    check('commercial_assignment_status_ui',await evaluate("document.querySelector('#content').textContent.includes('Contactado')"))
                    await action('Agregar actividad');await until("!!document.querySelector('dialog [name=text]')");await fill('text','Synthetic follow up note');await save_editor()
                    check('commercial_note_ui',True)
                    await action('Programar seguimiento');await until("!!document.querySelector('dialog [name=due_at]')")
                    from datetime import datetime,timedelta,timezone
                    due=(datetime.now(timezone(timedelta(hours=-5)))+timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M')
                    await fill('due_at',due);await fill('note','Synthetic task');await save_editor()
                    await open_commercial();await evaluate("[...document.querySelectorAll('dialog button')].find(b=>b.textContent==='Completar').click()")
                    await until("document.querySelectorAll('dialog').length===0")
                    check('commercial_task_complete_ui',True)
                    check('commercial_voucher_upload',await evaluate("(async()=>{const fixture=window.__commercialFixture;const config=await(await fetch('/api/config')).json();const blob=await(await fetch(config.assistant.logo_url)).blob();const form=new FormData();for(const [key,value] of Object.entries({carrera:'Contabilidad',concepto:'inscripcion',monto:'80',session_id:fixture.session.session_id,lead_id:fixture.lead_id}))form.append(key,value);form.append('imagen',new File([blob],'voucher.png',{type:'image/png'}));const r=await fetch('/api/vouchers',{method:'POST',headers:{'X-Session-Token':fixture.session.session_token,'Idempotency-Key':crypto.randomUUID()},body:form});const result=await r.json();fixture.voucher_id=result.voucher_id;return r.ok})()"))
                    check('commercial_voucher_review',await evaluate("(async()=>{const csrf=(await(await fetch('/api/admin/auth/csrf')).json()).csrf_token;return (await fetch('/api/admin/vouchers/'+window.__commercialFixture.voucher_id+'/review',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({status:'approved',review_note:'Synthetic review'})})).ok})()"))
                    await action('Estado y responsable');await until("!!document.querySelector('dialog [name=status]')");await fill('status','converted');await save_editor()
                    await open_commercial();check('commercial_timeline_integrated',await evaluate("['Lead creado','Responsable asignado','Estado cambiado','Nota agregada','Seguimiento programado','Seguimiento completado','Comprobante recibido','Comprobante aprobado','Conversión comercial registrada'].every(t=>document.querySelector('.lead-profile').textContent.includes(t))"))
                    image=await call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})
                    (output.parent/'fase-9d-lead.png').write_bytes(base64.b64decode(image['data']))
                    await evaluate("[...document.querySelectorAll('dialog button')].find(b=>b.textContent==='Cerrar').click()")
                    check('commercial_stale_admin_conflict',await evaluate("(async()=>{const id=window.__commercialFixture.lead_id;const old=await(await fetch('/api/admin/operations/leads/'+id)).json();const csrf=(await(await fetch('/api/admin/auth/csrf')).json()).csrf_token;const write=async assigned=>fetch('/api/admin/operations/leads/'+id,{method:'PUT',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf,'If-Match':old.etag,'Idempotency-Key':crypto.randomUUID()},body:JSON.stringify({status:'converted',assigned_to_user_id:assigned})});const a=await write(null),b=await write(null);return a.ok && b.status===409})()"))
                    await screen('vouchers');await evaluate("[...document.querySelectorAll('#content tr')].find(r=>r.textContent.includes('Pendiente')).querySelector('button').click()")
                    await until("document.querySelector('dialog img')?.complete")
                    check('voucher_image_private_ui',await evaluate("document.querySelector('dialog img').naturalWidth===4"))
                    await fill('review_note','Synthetic administrative review');await save_editor()
                    check('voucher_approved_ui',await evaluate("document.querySelector('#content').textContent.includes('Aprobado')"))
                    await screen('users');check('users_ui_roles',await evaluate("document.querySelector('#content').textContent.includes('Superadministrador')"))
                    await evaluate("[...document.querySelectorAll('#content button')].find(b=>b.textContent==='Nuevo usuario').click()")
                    await until("!!document.querySelector('dialog [name=username]')")
                    await fill('username','synthetic_new_user');await fill('display_name','Synthetic admissions');await fill('password',password);await fill('role','admisiones');await save_editor()
                    check('create_user_ui',await evaluate("document.querySelector('#content').textContent.includes('Synthetic admissions') && document.querySelector('#content').textContent.includes('Admisiones')"))
                    await evaluate("[...document.querySelectorAll('#content tbody tr')].find(r=>r.textContent.includes('synthetic_new_user')).querySelector('button').click()")
                    await until("!!document.querySelector('dialog [name=role]')");await fill('role','solo_lectura');await save_editor()
                    check('edit_user_role_ui',await evaluate("[...document.querySelectorAll('#content tbody tr')].find(r=>r.textContent.includes('synthetic_new_user')).textContent.includes('Sólo lectura')"))
                    await screen('audit')
                    await evaluate("document.querySelector('#content [name=resource_type]').value='prices';document.querySelector('#content form').requestSubmit()")
                    await until("document.querySelector('#content tbody')?.textContent.includes('Cambio de Inscripción')")
                    check('audit_ui_readable',await evaluate("document.querySelector('#content').textContent.includes('Cambio de Inscripción')"))
                    await screen('dashboard')
                    image=await call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})
                    (output.parent/'fase-9d-dashboard.png').write_bytes(base64.b64decode(image['data']))
                    await screen('programs')
                    await evaluate("document.querySelector('#content tbody button').click()")
                    await until("!!document.querySelector('dialog [name=name]')");await fill('name','Preserved draft fixture')
                    check('force_session_expiry_fixture',await evaluate("(async()=>{const csrf=(await(await fetch('/api/admin/auth/csrf')).json()).csrf_token;return (await fetch('/api/admin/auth/logout',{method:'POST',headers:{'X-CSRF-Token':csrf}})).status===204})()"))
                    await evaluate("document.querySelector('dialog form').requestSubmit()")
                    await until("!document.querySelector('#login').hidden")
                    check('expired_session_draft_notice',await evaluate("document.querySelector('#status').textContent.includes('borrador')"))
                    await evaluate("document.querySelector('#username').value='synthetic_admin';document.querySelector('#password').value="+json.dumps(password)+";document.querySelector('#login').requestSubmit()")
                    await until("document.querySelector('dialog')?.textContent.includes('Recuperar borrador')")
                    await evaluate("document.querySelector('dialog form').requestSubmit()")
                    await until("document.querySelector('dialog [name=name]')?.value==='Preserved draft fixture'")
                    check('same_identity_restores_draft',True)
                    await call('Input.dispatchKeyEvent',{'type':'keyDown','key':'Escape','code':'Escape','windowsVirtualKeyCode':27})
                    await call('Input.dispatchKeyEvent',{'type':'keyUp','key':'Escape','code':'Escape','windowsVirtualKeyCode':27})
                    await until("document.querySelectorAll('dialog').length===0")
                    check('escape_focus_return',await evaluate("document.activeElement?.id==='content' || document.querySelector('#content').contains(document.activeElement)"))
                    await call('Emulation.setDeviceMetricsOverride',{'width':768,'height':1024,'deviceScaleFactor':1,'mobile':False})
                    check('tablet_no_page_overflow',await evaluate("document.documentElement.scrollWidth<=window.innerWidth"))
                    await call('Emulation.setDeviceMetricsOverride',{'width':390,'height':844,'deviceScaleFactor':1,'mobile':True})
                    image=await call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})
                    (output.parent/'fase-9d-mobile.png').write_bytes(base64.b64decode(image['data']))
                    check('bounded_notifications',await evaluate("document.querySelector('#notifications').children.length<=2"))
                    check('mobile_menu',await evaluate("getComputedStyle(document.querySelector('#menu-toggle')).display!=='none' && document.documentElement.scrollWidth<=window.innerWidth"))
                    await call('Emulation.clearDeviceMetricsOverride')
                    await evaluate("document.querySelector('#logout').click()")
                    await until("!document.querySelector('#login').hidden && !document.querySelector('#login button').disabled")
                    check('logout_invalidates',await evaluate("(async()=> (await fetch('/api/admin/auth/me')).status===401)()"))
                    await login('synthetic_reader')
                    await screen('prices')
                    check('readonly_no_write_controls',await evaluate("![...document.querySelectorAll('#content button')].some(b=>['Editar','Nueva tarifa'].includes(b.textContent))"))
                    check('readonly_mutation_403',await evaluate("(async()=>{const p=(await(await fetch('/api/admin/programs')).json())[0];for(const k of ['created_at','updated_at','created_by','updated_by'])delete p[k];const csrf=(await(await fetch('/api/admin/auth/csrf')).json()).csrf_token;return (await fetch('/api/admin/programs/'+p.id,{method:'PUT',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(p)})).status===403})()"))
                    check('no_admin_credentials_in_storage',await evaluate("!Object.keys(localStorage).some(k=>/admin|token/i.test(k)) && !Object.keys(sessionStorage).filter(k=>k!=='av_kiosk_session_token').some(k=>/admin|token/i.test(k))"))
                    report['passed']=True
                    try: await call('Browser.close')
                    except websockets.ConnectionClosed: pass
            except Exception as exc:report['error_type']=type(exc).__name__;report['failure_code']=str(exc) if str(exc) in ('startup_failed','browser_protocol','browser_script','browser_condition') else 'check_failed'
            finally:
                for child in reversed(owned):
                    if child.poll() is None:
                        child.terminate()
                        try:child.wait(timeout=15)
                        except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report));return 0 if report['passed'] else 1
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    raise SystemExit(asyncio.run(execute(parser.parse_args().output)))
