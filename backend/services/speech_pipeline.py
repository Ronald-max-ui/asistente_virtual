"""Bounded speculative TTS; delivery remains strictly in sentence order."""
import asyncio
from dataclasses import dataclass
import anyio
from services.performance import current_trace

@dataclass
class SpeechJob:
    text: str
    audio: asyncio.Task

class OrderedSpeechPipeline:
    def __init__(self, source, synthesize, concurrency=2, pending=2):
        if not 1<=concurrency<=4 or not 1<=pending<=8:raise ValueError('Invalid TTS limits')
        self.source,self.synthesize=source,synthesize
        self.queue=asyncio.Queue(maxsize=pending)
        self.slots=asyncio.Semaphore(concurrency+pending)
        self.workers=asyncio.Semaphore(concurrency)
        self.tasks=set();self.producer=None;self.active=0;self.peak=0
    async def _audio(self,text):
        async with self.workers:
            self.active+=1;self.peak=max(self.peak,self.active)
            try:return await self.synthesize(text)
            finally:self.active-=1
    async def _produce(self):
        try:
            async for text in self.source:
                if not text:continue
                await self.slots.acquire()
                task=asyncio.create_task(self._audio(text));self.tasks.add(task)
                trace=current_trace.get()
                if trace:trace.values['pending_peak']=max(trace.values.get('pending_peak',0),len(self.tasks))
                await self.queue.put(SpeechJob(text,task))
            await self.queue.put(None)
        except asyncio.CancelledError:raise
        except Exception as exc:await self.queue.put(exc)
    async def __aiter__(self):
        self.producer=asyncio.create_task(self._produce())
        try:
            while True:
                job=await self.queue.get()
                if job is None:return
                if isinstance(job,Exception):raise job
                try:yield job
                finally:
                    if not job.audio.done():
                        await self.close()
                    self.tasks.discard(job.audio);self.slots.release()
        finally:
            await self.close()
    async def close(self):
        with anyio.CancelScope(shield=True):
            if self.producer:self.producer.cancel()
            for task in self.tasks:task.cancel()
            await asyncio.gather(*([self.producer] if self.producer else []),*self.tasks,return_exceptions=True)
            self.tasks.clear()
            while not self.queue.empty():self.queue.get_nowait()
            await self.source.aclose()
            trace=current_trace.get()
            if trace:trace.values['tts_active_peak']=self.peak
