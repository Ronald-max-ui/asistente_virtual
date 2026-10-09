"""Local headless Chrome benchmark; isolated profile, public data only."""
import argparse
import asyncio
import json
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
import websockets

async def benchmark(url,seconds=4,conversation=False,reload=False):
    chrome=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
    with tempfile.TemporaryDirectory(prefix='lia-browser-') as profile:
        process=subprocess.Popen([str(chrome),'--headless=new','--remote-debugging-port=0',
            '--user-data-dir='+profile,'--no-first-run','--no-default-browser-check',
            '--disable-extensions','--enable-unsafe-swiftshader','--window-size=1280,900','about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            active=Path(profile)/'DevToolsActivePort'
            for _ in range(100):
                if active.exists():break
                await asyncio.sleep(.1)
            port=int(active.read_text().splitlines()[0])
            endpoint=json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json/version'))['webSocketDebuggerUrl']
            async with websockets.connect(endpoint,max_size=20_000_000) as ws:
                serial=0;session=None;avatar_requests={}
                async def call(method,params=None):
                    nonlocal serial
                    serial+=1;message={'id':serial,'method':method,'params':params or {}}
                    if session:message['sessionId']=session
                    await ws.send(json.dumps(message))
                    while True:
                        response=json.loads(await ws.recv())
                        method_name=response.get('method')
                        details=response.get('params',{})
                        if method_name=='Network.responseReceived' and '/static/avatars/' in details['response']['url']:
                            metadata=details['response']
                            avatar_requests[details['requestId']]={'status':metadata['status'],'disk_cache':metadata.get('fromDiskCache',False)}
                        if method_name=='Network.loadingFinished' and details['requestId'] in avatar_requests:
                            avatar_requests[details['requestId']]['network_bytes']=details['encodedDataLength']
                        if response.get('id')==serial:
                            if 'error' in response:raise RuntimeError(method+': '+str(response['error']))
                            return response.get('result',{})
                target=await call('Target.createTarget',{'url':'about:blank'})
                attached=await call('Target.attachToTarget',{'targetId':target['targetId'],'flatten':True});session=attached['sessionId']
                await call('Page.enable');await call('Runtime.enable');await call('Network.enable')
                await call('Page.addScriptToEvaluateOnNewDocument',{'source':"""
window.__liaBench={frames:0,draws:0,shader_ms:0,texture_ms:0,avatar_ms:null};
const raf=window.requestAnimationFrame.bind(window);
window.requestAnimationFrame=(cb)=>raf((t)=>{window.__liaBench.frames++;cb(t)});
window.__liaBench.conversation=null;
const debug=console.debug.bind(console);
console.debug=(...args)=>{if(args[0]==='[performance]')window.__liaBench.conversation=args[1];debug(...args)};
const log=console.log.bind(console);
console.log=(...args)=>{if(args.some(a=>String(a).includes('Modelo VRM cargado')))window.__liaBench.avatar_ms=performance.now();log(...args)};
for(const klass of [window.WebGLRenderingContext,window.WebGL2RenderingContext]){
 if(!klass)continue;
 for(const [name,key] of [['compileShader','shader_ms'],['texImage2D','texture_ms'],['drawElements','draws']]){
  const original=klass.prototype[name];if(!original)continue;
  klass.prototype[name]=function(...args){const start=performance.now();const result=original.apply(this,args);if(key==='draws')window.__liaBench.draws++;else window.__liaBench[key]+=performance.now()-start;return result};
 }
}
"""})
                if conversation:
                    await call('Page.addScriptToEvaluateOnNewDocument',{'source':"""
window.SpeechRecognition=class {
 start(){this.onstart?.();setTimeout(()=>this.onresult?.({results:[[{transcript:'¿Qué se aprende en Administración?'}]]}),10)}
 stop(){this.onend?.()} abort(){}
};
"""})
                await call('Page.navigate',{'url':url})
                visible=False
                for _ in range(200):
                    value=await call('Runtime.evaluate',{'expression':'Boolean(window.__liaBench?.avatar_ms)','returnByValue':True})
                    if value.get('result',{}).get('value'):visible=True;break
                    await asyncio.sleep(.1)
                expression="""JSON.stringify({timings:window.__liaBench,heap_bytes:performance.memory?.usedJSHeapSize,navigation:performance.getEntriesByType('navigation').map(x=>({dom_ms:x.domContentLoadedEventEnd,load_ms:x.loadEventEnd})),resources:performance.getEntriesByType('resource').map(x=>({name:x.name.split('/').pop(),duration_ms:x.duration,start_ms:x.startTime,end_ms:x.responseEnd,transfer_bytes:x.transferSize,body_bytes:x.encodedBodySize})),paint:performance.getEntriesByType('paint').map(x=>({name:x.name,ms:x.startTime})),marks:performance.getEntriesByType('measure').map(x=>({name:x.name,ms:x.duration}))})"""
                result=await call('Runtime.evaluate',{'expression':expression,'returnByValue':True})
                before=json.loads(result['result']['value'])
                if conversation and visible:
                    await call('Runtime.evaluate',{'expression':"document.getElementById('mic-btn').click()",'userGesture':True})
                    for _ in range(450):
                        check=await call('Runtime.evaluate',{'expression':'Boolean(window.__liaBench.conversation)','returnByValue':True})
                        if check.get('result',{}).get('value'):break
                        await asyncio.sleep(.2)
                    measured=await call('Runtime.evaluate',{'expression':'JSON.stringify(window.__liaBench.conversation)','returnByValue':True})
                    before['conversation']=json.loads(measured['result']['value'])
                snapshot=await call('Runtime.evaluate',{'expression':'JSON.stringify(window.__liaBench)','returnByValue':True})
                render_start=json.loads(snapshot['result']['value'])
                await asyncio.sleep(seconds)
                value=await call('Runtime.evaluate',{'expression':'JSON.stringify(window.__liaBench)','returnByValue':True});after=json.loads(value['result']['value'])
                await call('Runtime.evaluate',{'expression':"Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});document.dispatchEvent(new Event('visibilitychange'))"})
                await asyncio.sleep(seconds)
                value=await call('Runtime.evaluate',{'expression':'JSON.stringify(window.__liaBench)','returnByValue':True});hidden=json.loads(value['result']['value'])
                await call('Runtime.evaluate',{'expression':"Object.defineProperty(document,'hidden',{configurable:true,get:()=>false});document.dispatchEvent(new Event('visibilitychange'))"})
                await asyncio.sleep(1)
                value=await call('Runtime.evaluate',{'expression':'JSON.stringify(window.__liaBench)','returnByValue':True});resumed=json.loads(value['result']['value'])
                before['resume_frames']=resumed['frames']-hidden['frames']
                parse=await call('Runtime.evaluate',{'expression':"JSON.stringify((()=>{const sample=JSON.stringify({type:'audio',audio_b64:btoa('a'.repeat(5120))});let start=performance.now();for(let i=0;i<1000;i++)JSON.parse(sample);const json_ms=(performance.now()-start)/1000;start=performance.now();for(let i=0;i<1000;i++)atob(JSON.parse(sample).audio_b64);return {original_bytes:5120,base64_bytes:6828,json_parse_ms:json_ms,json_plus_decode_ms:(performance.now()-start)/1000};})())",'returnByValue':True})
                before['audio_transfer']=json.loads(parse['result']['value'])
                before['avatar_network']=list(avatar_requests.values())
                if reload:
                    avatar_requests.clear();await call('Page.reload')
                    for _ in range(200):
                        value=await call('Runtime.evaluate',{'expression':'Boolean(window.__liaBench?.avatar_ms)','returnByValue':True})
                        if value.get('result',{}).get('value'):break
                        await asyncio.sleep(.1)
                    value=await call('Runtime.evaluate',{'expression':expression,'returnByValue':True})
                    before['warm_reload']=json.loads(value['result']['value'])
                    before['warm_reload']['avatar_network']=list(avatar_requests.values())
                before['visible']=visible;before['render_test']={'seconds':seconds,'visible_frames':after['frames']-render_start['frames'],'hidden_frames':hidden['frames']-after['frames'],'hidden_draws':hidden['draws']-after['draws']};before['environment']='headless Chrome, localhost, software GPU; hidden simulated via visibilitychange'
                return before
        finally:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()
            await asyncio.sleep(.2)

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--url',default='http://localhost:5173/?mode=kiosk');parser.add_argument('--output',type=Path,required=True);parser.add_argument('--reload',action='store_true',help='Measure avatar cache on a second navigation');parser.add_argument('--conversation',action='store_true',help='One synthetic microphone query with real backend providers');args=parser.parse_args()
 result=asyncio.run(benchmark(args.url,conversation=args.conversation,reload=args.reload));args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
