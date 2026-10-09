"""Public asset caching; private responses remain no-store in security middleware."""
import re
from fastapi.staticfiles import StaticFiles
class PublicStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        query = scope.get('query_string', b'').decode('ascii', errors='ignore')
        versioned = bool(re.fullmatch(r'v=[a-f0-9]{64}', query))
        response.headers['Cache-Control'] = 'public, max-age=31536000, immutable' if versioned else 'public, no-cache'
        return response
