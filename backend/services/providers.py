"""Provider ports with callable adapters for Groq, Edge-TTS and academic RAG."""
from dataclasses import dataclass
from typing import Protocol, Any

@dataclass(frozen=True)
class LLMDelta:
    content: str = ''
    tool_calls: Any = None
    truncated: bool = False
    tokens: int | None = None

class LLMProvider(Protocol):
    async def complete(self, *args, **kwargs): ...
    async def stream(self, *args, **kwargs): ...
    def delta(self, chunk) -> LLMDelta: ...

class SpeechProvider(Protocol):
    async def synthesize(self, text: str) -> bytes: ...

class KnowledgeProvider(Protocol):
    async def search(self, question: str, history: list) -> str: ...

@dataclass
class GroqProvider:
    complete_call: Any
    stream_call: Any
    async def complete(self, *args, **kwargs):
        return await self.complete_call(*args, **kwargs)
    async def stream(self, *args, **kwargs):
        return await self.stream_call(*args, **kwargs)
    def delta(self, chunk):
        usage=getattr(chunk,'usage',None) or getattr(getattr(chunk,'x_groq',None),'usage',None)
        tokens=getattr(usage,'completion_tokens',None)
        if not chunk.choices: return LLMDelta(tokens=tokens)
        choice = chunk.choices[0]
        return LLMDelta(getattr(choice.delta, 'content', None) or '',
            getattr(choice.delta, 'tool_calls', None), getattr(choice, 'finish_reason', None) == 'length',tokens)

@dataclass
class EdgeSpeechProvider:
    audio_call: Any
    async def synthesize(self, text): return await self.audio_call(text)

@dataclass
class AcademicKnowledgeProvider:
    search_call: Any
    warmup_call: Any = None
    async def search(self, question, history): return await self.search_call(question, history)
    async def warmup(self):
        if self.warmup_call is not None:await self.warmup_call()

@dataclass
class ConfiguredEdgeSpeechProvider(EdgeSpeechProvider):
    voice_service: Any
    def snapshot(self):return self.voice_service.snapshot()
    async def synthesize_configured(self,text,voice):
        if not voice or not voice.get('enabled'):raise RuntimeError('Speech disabled or degraded')
        return await self.audio_call(text,voice=voice)
    async def synthesize(self,text):return await self.synthesize_configured(text,self.snapshot())
