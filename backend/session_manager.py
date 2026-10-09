"""Session service: opaque credentials, persisted ownership and local cancellation."""
import asyncio
import hashlib
import secrets
import uuid
from domain.errors import SessionError
import anyio
from persistence.runtime_repository import RuntimeConflict
from persistence.sqlite_runtime_repository import SQLiteRuntimeRepository


def token_digest(token):
    return hashlib.sha256((token or '').encode()).hexdigest()


from runtime_config import SessionSettings

def runtime_path(): return SessionSettings.from_env().path


class SessionManager:
    def __init__(self, ttl=1800, cleanup_interval=60, repository=None):
        config = SessionSettings.from_env()
        self.repository = repository or SQLiteRuntimeRepository(config.path,
            inactivity=ttl, lifetime=config.lifetime, max_turns=config.persisted_turns,
            max_chars=config.history_chars, lease=config.request_lease)
        self._cleanup_interval = cleanup_interval
        self.tasks = {}

    async def call(self, method, *args, **kwargs):
        try:
            return await asyncio.to_thread(getattr(self.repository, method), *args, **kwargs)
        except RuntimeConflict as exc:
            raise SessionError(exc.code, exc.status) from exc

    async def bootstrap(self, sid=None, token=None):
        if token and sid:
            await self.authorize(sid, token)
            return {'session_id': sid, 'session_token': token}
        sid = sid or uuid.uuid4().hex
        token = secrets.token_urlsafe(32)
        await self.call('create_session', sid, token_digest(token))
        return {'session_id': sid, 'session_token': token}

    async def authorize(self, sid, token):
        if not token or len(token) > 128:
            raise SessionError('session_unauthorized', 401)
        return await self.call('authorize', sid, token_digest(token))

    async def begin(self, sid, persona, replace=False, key=None):
        # Don't abandon a successful DB claim if the HTTP task disconnects while
        # its SQLite worker is finishing the transaction.
        pending = asyncio.create_task(self.call('begin', sid, persona, replace, key))
        try:
            rid, old = await asyncio.shield(pending)
        except asyncio.CancelledError:
            with anyio.CancelScope(shield=True):
                rid, _ = await pending
                await self.call('release', sid, rid)
            raise
        if old:
            self._cancel_task(old)
        return rid

    def bind(self, rid):
        self.tasks[rid] = asyncio.current_task()

    def _cancel_task(self, rid):
        task = self.tasks.get(rid)
        if task and task is not asyncio.current_task() and not task.done():
            task.get_loop().call_soon_threadsafe(task.cancel)

    async def current(self, sid, rid):
        await self.call('current', sid, rid)

    async def finish(self, sid, rid, question, answer, actions):
        await self.call('finish', sid, rid, question, answer, actions)

    async def release(self, sid, rid):
        self.tasks.pop(rid, None)
        with anyio.CancelScope(shield=True):
            await self.call('release', sid, rid)

    async def watch_disconnect(self, sid, rid, request):
        """JSON has no StreamingResponse task group to watch disconnects."""
        while True:
            await asyncio.sleep(.5)
            try:
                await self.current(sid, rid)
                if await request.is_disconnected():
                    await self.cancel(sid, rid)
                    return
            except SessionError:
                self._cancel_task(rid)
                return

    async def obtener_sesion(self, sid):
        return await self.call('snapshot', sid)

    async def cancel(self, sid, rid=None, reset=False, key=None):
        result, old = await self.call('cancel', sid, rid, reset, key)
        if old:
            self._cancel_task(old)
        return result

    async def limpiar_expiradas(self):
        rows = await self.call('cleanup')
        for row in rows:
            if row['active_request_id']:
                self._cancel_task(row['active_request_id'])
        return len(rows)

    async def iniciar_limpieza_periodica(self):
        while True:
            try:
                await self.limpiar_expiradas()
            except Exception as exc:
                from security.logging import safe_event
                safe_event('session_cleanup_failed', error=exc)
            await asyncio.sleep(self._cleanup_interval)
