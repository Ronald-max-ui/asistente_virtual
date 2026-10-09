"""Puerto reemplazable por Redis; contador de ventana móvil acotado en memoria."""
import math
import time
from collections import deque
from threading import RLock
from typing import Protocol

class RateLimitStore(Protocol):
    def consume(self, key: str, limit: int, window: int) -> int: ...

class MemoryRateLimitStore:
    def __init__(self, max_keys=10000, clock=time.monotonic):
        self.max_keys, self.clock = max_keys, clock
        self.entries = {}
        self.lock = RLock()
    def consume(self, key, limit, window):
        with self.lock:
            now = self.clock()
            if len(self.entries) >= self.max_keys and key not in self.entries:
                self.entries = {k: (q, w) for k, (q, w) in self.entries.items() if q and q[-1] > now - w}
                if len(self.entries) >= self.max_keys:
                    return window  # No expulsar contadores activos y permitir evasión.
            queue, old_window = self.entries.setdefault(key, (deque(), window))
            while queue and queue[0] <= now - window:
                queue.popleft()
            self.entries[key] = (queue, window)
            if len(queue) >= limit:
                return max(1, math.ceil(queue[0] + window - now))
            queue.append(now)
            return 0

def endpoint_group(path):
    if path == '/chat' or path == '/chat/stream': return 'chat'
    if path == '/api/leads': return 'leads'
    if path == '/api/vouchers': return 'vouchers'
    if path == '/api/admin/auth/login': return 'admin_login'
    if path == '/api/admin' or path.startswith('/api/admin/'): return 'admin'
    if path in ('/reset-session','/api/session/cancel'): return 'reset'
    if path == '/api/session': return 'public'
    if path in ('/api/config', '/api/media'): return 'public'
    if path.startswith('/static/'): return 'static'
    return None
