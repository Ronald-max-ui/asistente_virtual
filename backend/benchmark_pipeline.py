"""Reproducible component benchmark; simulated providers by default, no PII output."""
import argparse
import asyncio
import base64
import contextlib
import io
import json
import logging
import statistics
import tempfile
import time
import tracemalloc
import types
from pathlib import Path
from app_services import build_services
from session_manager import SessionManager
from persistence.sqlite_runtime_repository import SQLiteRuntimeRepository
from services.providers import GroqProvider, EdgeSpeechProvider, AcademicKnowledgeProvider
from services.pricing_service import PricingService
from security.inputs import ChatInput
from security.config import SecuritySettings
from security.logging import logger

async def measure(runs=5, real=False, stress=0, prewarm=False):
    from config import settings
    samples=[]
    delay=0 if stress else 0.02
    logger.setLevel(logging.ERROR)
    with tempfile.TemporaryDirectory() as directory:
        sessions=SessionManager(repository=SQLiteRuntimeRepository(Path(directory)/'runtime.sqlite3'))
        timestamps={};identity=None
        async def knowledge(question,history):
            began=time.perf_counter(); await asyncio.sleep(delay/2)
            timestamps['rag_ms']=(time.perf_counter()-began)*1000
            return 'Información académica de talleres.'
        async def stream(*args,**kwargs):
            async def chunks():
                started=time.perf_counter();timestamps['llm_started']=started
                for i in range(6):
                    await asyncio.sleep(delay)
                    timestamps.setdefault('llm_first_token_ms',(time.perf_counter()-started)*1000)
                    delta=types.SimpleNamespace(content='Información académica confirmada. ',tool_calls=None)
                    yield types.SimpleNamespace(choices=[types.SimpleNamespace(delta=delta)])
                yield types.SimpleNamespace(choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content=None,tool_calls=[types.SimpleNamespace(index=0,function=types.SimpleNamespace(name='show_gallery',arguments='{"resource_id":"gastronomia_talleres"}'))]))])
                timestamps['llm_total_ms']=(time.perf_counter()-started)*1000
            return chunks()
        async def speech(text):
            began=time.perf_counter();await asyncio.sleep(delay*5)
            elapsed=(time.perf_counter()-began)*1000
            timestamps.setdefault('tts_first_sentence_ms',elapsed)
            timestamps['tts_total_ms']=timestamps.get('tts_total_ms',0)+elapsed
            return b'audio'*1024
        dependencies={} if real else dict(llm=GroqProvider(None,stream),speech=EdgeSpeechProvider(speech),knowledge=AcademicKnowledgeProvider(knowledge))
        services=build_services(settings,session=sessions,voucher_directory=Path(directory)/'vouchers',**dependencies)
        from dataclasses import replace
        limits=replace(SecuritySettings(),stream_timeout=90)
        warm_ms=None
        if prewarm:
            from dataclasses import replace
            services.conversation.performance=replace(services.conversation.performance,knowledge_prewarm=True)
            start=time.perf_counter();await services.warmup(limits.rag_timeout);warm_ms=(time.perf_counter()-start)*1000
        tracemalloc.start();before=tracemalloc.get_traced_memory()[0]
        try:
            for i in range(stress or runs):
                timestamps.clear();start=time.perf_counter()
                identity=await sessions.bootstrap(identity['session_id'],identity['session_token']) if stress and identity else await sessions.bootstrap();bootstrap=(time.perf_counter()-start)*1000
                turn=await services.conversation.prepare(ChatInput(mensaje='Muéstrame fotos de los talleres de Gastronomía',session_id=identity['session_id'],mode='kiosk'),identity['session_token'])
                count=0;raw_bytes=0;b64_bytes=0;first_text=None;first_audio=None;actions=None;audio_last=None;completed=False
                async for event in services.conversation.events(turn,limits):
                    elapsed=(time.perf_counter()-start)*1000
                    if event['type']=='text' and first_text is None:first_text=elapsed
                    if event['type']=='audio':
                        count+=1;audio_last=elapsed;b64_bytes+=len(event['audio_b64']);raw_bytes+=len(base64.b64decode(event['audio_b64']))
                        if first_audio is None:first_audio=elapsed
                    if event['type']=='ui_action':actions=elapsed
                    if event['type']=='done':completed=True
                sample=dict(turn.trace.values)
                sample.update({k:v for k,v in timestamps.items() if k.endswith('_ms') and k!='tts_first_sentence_ms'})
                sample.update(session_bootstrap_ms=bootstrap,first_text_ms=first_text,first_audio_ms=first_audio,
                    audio_total_ms=audio_last,actions_ms=actions,total_ms=(time.perf_counter()-start)*1000,
                    audio_original_bytes=raw_bytes,audio_base64_bytes=b64_bytes,audio_events=count,completed=int(completed))
                samples.append(sample)
            retained,peak=tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop();await services.close()
        result={'providers':'real' if real else 'simulated','runs':len(samples),'startup_warm_ms':warm_ms,'samples':samples,
            'median':{key:round(statistics.median(s[key] for s in samples if s.get(key) is not None),3)
                for key in samples[0] if any(s.get(key) is not None for s in samples)},
            'memory':{'retained_delta_bytes':retained-before,'peak_bytes':peak,'active_tasks_after':len(sessions.tasks),'last_history_turns':len(sessions.repository.snapshot(identity['session_id'])['history'])//2}}
        return result

async def rewrite_measure():
    """One fixed ambiguous follow-up; no returned text or provider payload."""
    from services.rag_service import reformular_query
    from services.llm_service import create_client
    from services.knowledge_retrieval import detectar_entidad
    from services.performance import PerformanceTrace, current_trace
    client=create_client();trace=PerformanceTrace();token=current_trace.set(trace)
    try:
        reformulated=await reformular_query('¿Y los requisitos?',
            [{'role':'user','content':'Información de Gastronomía'},{'role':'assistant','content':'Formación presencial en talleres.'}],client=client)
        return {'duration_ms':trace.values.get('rag_reformulation_ms'),
                'resolved_program':int(detectar_entidad(reformulated)=='gastronomia'),'samples':1}
    finally:
        await client.close();current_trace.reset(token)

def rag_measure():
    from services.knowledge_index import KnowledgeIndex
    index=KnowledgeIndex();before=time.perf_counter();index.search('¿Qué se aprende en Administración?','administracion')
    cold=(time.perf_counter()-before)*1000;embeddings=[];samples=[]
    original=index._embedder.query_embed
    def counted(*args,**kwargs):
        start=time.perf_counter();values=list(original(*args,**kwargs));embeddings.append((time.perf_counter()-start)*1000);return iter(values)
    index._embedder.query_embed=counted
    for _ in range(5):
        start=time.perf_counter();index.search('¿Qué se aprende en Administración?','administracion');samples.append((time.perf_counter()-start)*1000)
    return {'cold_ms':round(cold,3),'warm_median_ms':round(statistics.median(samples),3),
        'embedding_median_ms':round(statistics.median(embeddings),3),'query_count':len(samples),'embedding_count':len(embeddings)}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--runs',type=int,default=5)
    parser.add_argument('--real',action='store_true');parser.add_argument('--prewarm',action='store_true');parser.add_argument('--rewrite',action='store_true');parser.add_argument('--rag',action='store_true');parser.add_argument('--stress',type=int,default=0);parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if not 1<=args.runs<=100 or not 0<=args.stress<=1000:parser.error('Runs fuera de rango')
    if args.rewrite and not args.real:parser.error('--rewrite requires --real')
    result=asyncio.run(measure(args.runs,args.real,args.stress,args.prewarm))
    if args.rewrite:result['rewrite_real']=asyncio.run(rewrite_measure())
    if args.rag:result['rag_real']=rag_measure()
    encoded=json.dumps(result,ensure_ascii=False,indent=2)
    if args.output:args.output.write_text(encoded+'\n',encoding='utf-8')
    print(encoded)
if __name__=='__main__':main()
