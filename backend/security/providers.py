"""Espera total e inactividad acotadas, con cierre de recursos de streaming."""
import asyncio
from domain.errors import ProviderTimeout, ProviderUnavailable
from security.logging import safe_event

async def bounded_call(awaitable, timeout):
    return await asyncio.wait_for(awaitable, timeout)

async def provider_call(awaitable, timeout):
    try:
        return await bounded_call(awaitable, timeout)
    except TimeoutError as exc:
        safe_event('provider_timeout', error=exc)
        raise ProviderTimeout() from exc
    except Exception as exc:
        safe_event('provider_failed', error=exc)
        raise ProviderUnavailable() from exc

async def bounded_stream(stream, timeout):
    iterator = stream.__aiter__()
    try:
        while True:
            try:
                yield await asyncio.wait_for(anext(iterator), timeout)
            except StopAsyncIteration:
                return
    finally:
        await close_stream(stream)

async def close_stream(stream):
    close = getattr(stream, 'close', None) or getattr(stream, 'aclose', None)
    if close:
        try:
            result = close()
            if hasattr(result, '__await__'):
                await asyncio.wait_for(result, 2)
        except Exception as exc:
            safe_event('stream_close_failed', error=exc)
