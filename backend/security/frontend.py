"""Frontend deployment policy, also exercised by isolated production-build E2E.
Reverse proxy is authoritative in the recommended deployment.
"""
FRONTEND_CSP="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; font-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
class FrontendHeaders:
    def __init__(self,app):self.app=app
    async def __call__(self,scope,receive,send):
        path=scope.get('path','')
        private=any(path==prefix or path.startswith(prefix+'/') for prefix in ('/api','/admin','/chat','/health','/reset-session','/static'))
        if scope['type']!='http' or private:return await self.app(scope,receive,send)
        async def response(message):
            if message['type']=='http.response.start':
                headers=[(k,v) for k,v in message.get('headers',[]) if k.lower() not in (b'content-security-policy',b'cache-control')]
                cache=b'public, max-age=31536000, immutable' if path.startswith('/assets/') else b'no-cache'
                message={**message,'headers':headers+[(b'content-security-policy',FRONTEND_CSP.encode()),(b'cache-control',cache)]}
            await send(message)
        await self.app(scope,receive,response)
