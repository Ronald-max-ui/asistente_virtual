"""Shared conversation policy with JSON and streaming execution adapters.
HTTP encoding is intentionally outside this service; cancellation/commit fencing
remains here alongside the session that owns the operation.
"""
import asyncio
import anyio
import base64
import time
from dataclasses import dataclass
from domain.errors import SessionError
from services.performance import PerformanceTrace, current_trace, duration
from services.speech_pipeline import OrderedSpeechPipeline
from runtime_config import PerformanceSettings
from security.logging import safe_event
from security.providers import bounded_call, bounded_stream, close_stream, provider_call
from services.action_service import ActionContext
from services.llm_protocol import AssistantReply, LegacyActionAdapter, StreamAssembly, seleccionar_solicitudes
from services.intent_service import PERSONA_INFO, PERSONA_SALES, detectar_intencion_comercial, normalizar_persona

@dataclass
class ConversationTurn:
    session_id: str
    request_id: str
    question: str
    mode: str
    persona: str
    escalated: bool
    session: dict
    history: list
    shown: list
    context: ActionContext
    trace: PerformanceTrace
    voice: dict | None = None

class ConversationService:
    def __init__(self, sessions, llm, speech, knowledge, actions, pricing_policy, history_turns=4, performance=None):
        self.performance = performance or PerformanceSettings.from_env()
        self.sessions, self.llm, self.speech, self.knowledge = sessions, llm, speech, knowledge
        self.actions, self.pricing_policy, self.history_turns = actions, pricing_policy, history_turns

    async def rag(self, turn, config):
        started=time.perf_counter()
        try:return await provider_call(self.knowledge.search(turn.question, turn.history), config.rag_timeout)
        finally:duration('rag_ms',started)

    def provider_arguments(self, turn):
        return dict(mode=turn.mode, persona=turn.persona, shown_media=turn.shown,
            funnel_stage=turn.session.get('funnel_stage', 'discovery'), lead_submitted=turn.context.lead_submitted)

    def resolve_actions(self, requests, turn):
        return self.actions.process(requests, turn.context)

    def supplements(self, text, turn, result=None):
        if result is None:
            commercial = self.pricing_policy.answer(turn.question, turn.history)
            return commercial if commercial and commercial not in text else ''
        fallback = self.actions.fallback(result)
        return fallback if fallback and (result.notices or len(text) < 10) else ''

    async def audio(self, text, config, *, first_sentence=True, voice=None):
        started=time.perf_counter()
        try:
            call=self.speech.synthesize_configured(text,voice) if hasattr(self.speech,'synthesize_configured') else self.speech.synthesize(text)
            audio = await bounded_call(call, config.tts_timeout)
            trace=current_trace.get()
            if trace:
                trace.add('audio_original_bytes',len(audio));trace.add('audio_base64_bytes',4*((len(audio)+2)//3))
                trace.add('tts_sentences',1)
            return base64.b64encode(audio).decode()
        except Exception:
            safe_event('tts_unavailable')
            return None
        finally:
            trace=current_trace.get()
            if trace and first_sentence:trace.first('tts_first_sentence_ms',started)
            duration('tts_total_ms',started)

    async def commit(self, turn, text, actions):
        await self.sessions.finish(turn.session_id, turn.request_id, turn.question, text, actions)

    async def prepare(self, data, token):
        trace=PerformanceTrace()
        pregunta = data.mensaje.strip()
        mode = (data.mode or "web").lower()
        identity = await self.sessions.authorize(data.session_id, token)
        persona = normalizar_persona(data.persona, default=identity.get("persona") or (PERSONA_INFO if mode == "kiosk" else PERSONA_SALES))
        escalated = persona == PERSONA_INFO and detectar_intencion_comercial(pregunta)
        if escalated:
            persona = PERSONA_SALES
        rid = await self.sessions.begin(data.session_id, persona, data.replace_active, data.idempotency_key)
        try:
            session = await self.sessions.obtener_sesion(data.session_id)
        except BaseException:
            await self.sessions.release(data.session_id, rid)
            raise
        history = session["history"][-2 * self.history_turns:]
        shown = list(session.get("shown_media", []))
        context = ActionContext(pregunta, history, mode, persona, bool(session.get("lead_submitted", False)), shown)

        trace.operation=rid;trace.first('session_prepare_ms')
        return ConversationTurn(data.session_id, rid, pregunta, mode, persona, escalated, session, history, shown, context, trace, getattr(self.speech,'snapshot',lambda:None)())

    async def events(self, turn, config):
        rid, pregunta, history = turn.request_id, turn.question, turn.history
        persona, escalated = turn.persona, turn.escalated
        self.sessions.bind(rid)
        stream = None
        pipeline = None
        metric_token=current_trace.set(turn.trace)
        async def emit(payload):
            await self.sessions.current(turn.session_id, rid)
            metric={'text':'first_text_ms','audio':'first_audio_ms','ui_action':'actions_ms'}.get(payload['type'])
            if metric:turn.trace.first(metric)
            return {**payload, "request_id": rid}
        assembly = StreamAssembly(pregunta, history, self.pricing_policy.service)
        spoken = []
        async def sentence_events(sentence, *, trusted=False):
            sentence = sentence.strip() if trusted else self.pricing_policy.clean(sentence.strip(), pregunta, history)
            if not sentence:
                return
            spoken.append(sentence)
            yield await emit({"type": "text", "text": sentence})
            audio = await self.audio(sentence, config, voice=turn.voice)
            if audio is not None:
                yield await emit({"type": "audio", "audio_b64": audio})
        try:
            async with asyncio.timeout(config.stream_timeout):
                await self.sessions.current(turn.session_id, rid)
                if escalated:
                    yield await emit({"type":"mode_switch", "mode":persona})
                if not pregunta:
                    yield await emit({"type": "done", "full_text": "En que carrera o curso estas interesado?"})
                    return
                rag = await self.rag(turn, config)
                await self.sessions.current(turn.session_id, rid)
                llm_started=time.perf_counter()
                stream = await provider_call(self.llm.stream(history, rag, pregunta, **self.provider_arguments(turn)), config.groq_timeout)
                turn.trace.first('llm_open_ms',llm_started)
                requests=[]
                async def sentences():
                    nonlocal requests
                    try:
                        async for chunk in bounded_stream(stream, config.provider_idle_timeout):
                            delta=self.llm.delta(chunk)
                            if delta.content:turn.trace.first('llm_first_token_ms',llm_started)
                            if delta.tokens is not None:turn.trace.values['llm_tokens']=delta.tokens
                            for sentence in assembly.accept(delta):
                                yield self.pricing_policy.clean(sentence.strip(),pregunta,history)
                        tail,requests=assembly.finish()
                        if tail.strip():yield self.pricing_policy.clean(tail.strip(),pregunta,history)
                    finally:duration('llm_total_ms',llm_started)
                sentence_number=0
                async def synthesize_sentence(text):
                    nonlocal sentence_number
                    first=sentence_number==0;sentence_number+=1
                    return await self.audio(text,config,first_sentence=first,voice=turn.voice)
                pipeline=OrderedSpeechPipeline(sentences(),synthesize_sentence,
                    self.performance.tts_concurrency,self.performance.tts_pending)
                async for job in pipeline:
                    spoken.append(job.text)
                    yield await emit({'type':'text','text':job.text})
                    audio=await job.audio
                    if audio is not None:yield await emit({'type':'audio','audio_b64':audio})
                commercial = self.supplements(" ".join(spoken), turn)
                if commercial:
                    async for event in sentence_events(commercial, trusted=True):
                        yield event
                result = self.resolve_actions(requests, turn)
                fallback = self.supplements(" ".join(spoken), turn, result)
                if fallback:
                    async for event in sentence_events(fallback, trusted=True):
                        yield event
                await self.sessions.current(turn.session_id, rid)
                for action in result.actions:
                    yield await emit({"type": "ui_action", "action": action})
                for notice in result.notices:
                    yield await emit({"type": "notice", **notice})
                assistant_text = " ".join(spoken)
                await self.commit(turn, assistant_text, result.actions)
                yield await emit({"type": "done", "full_text": assistant_text})
        except asyncio.CancelledError:
            raise
        except Exception:
            safe_event('stream_failed')
            try:
                yield await emit({"type": "error", "message": "Error procesando la consulta."})
            except SessionError:
                pass  # Old/expired operation: no more events or actions.
        finally:
            # Starlette cancels its task group on disconnect; shield cleanup so
            # provider closure and conditional DB release still complete.
            with anyio.CancelScope(shield=True):
                try:
                    if pipeline is not None:await pipeline.close()
                    if stream is not None:
                        await close_stream(stream)
                finally:
                    await self.sessions.release(turn.session_id, rid)
                    turn.trace.report();current_trace.reset(metric_token)

    async def complete(self, turn, config, request):
        rid, pregunta, history = turn.request_id, turn.question, turn.history
        self.sessions.bind(rid)
        metric_token=current_trace.set(turn.trace)
        disconnect_task = asyncio.create_task(self.sessions.watch_disconnect(turn.session_id, rid, request))
        try:
            if not pregunta:
                return {"request_id":rid, "texto":"En que carrera o curso estas interesado?", "audio_b64":"", "actions":[], "notices":[]}
            rag = await self.rag(turn, config)
            llm_started=time.perf_counter()
            reply = await provider_call(self.llm.complete(history, rag, pregunta, **self.provider_arguments(turn)), config.groq_timeout)
            duration('llm_total_ms',llm_started)
            # Compatibilidad temporal con proveedores/rutas que aún retornan texto legado.
            reply = AssistantReply(assistant_text=reply) if isinstance(reply, str) else reply
            adapter = LegacyActionAdapter(pregunta, history, pricing=self.pricing_policy.service)
            assistant_text = self.pricing_policy.clean((adapter.feed(reply.assistant_text) + adapter.finish()).strip(), pregunta, history)
            commercial = self.supplements(assistant_text, turn)
            if commercial:
                assistant_text = (assistant_text + " " + commercial).strip()
            result = self.resolve_actions(seleccionar_solicitudes(reply.structured_actions, adapter.structured_actions, native_present=reply.native_actions_present), turn)
            fallback = self.supplements(assistant_text, turn, result)
            if fallback:
                assistant_text = (assistant_text + " " + fallback).strip()
            turn.trace.first('first_text_ms');turn.trace.first('actions_ms')
            audio_b64 = await self.audio(assistant_text, config, voice=turn.voice) or ''
            if audio_b64:turn.trace.first('first_audio_ms')
            await self.commit(turn, assistant_text, result.actions)
            return {"request_id":rid, "texto": assistant_text, "audio_b64": audio_b64, "actions": result.actions, "notices": result.notices}
        finally:
            with anyio.CancelScope(shield=True):
                disconnect_task.cancel()
                await asyncio.gather(disconnect_task, return_exceptions=True)
                await self.sessions.release(turn.session_id, rid)
            turn.trace.report();current_trace.reset(metric_token)
