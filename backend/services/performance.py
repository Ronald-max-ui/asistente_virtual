"""Numeric-only technical measurements. No content, identity or credentials."""
import time
import math
from contextvars import ContextVar
from security.logging import safe_event, request_id
current_trace=ContextVar('performance_trace',default=None)
FIELDS={'session_bootstrap_ms','session_prepare_ms','rag_ms','embedding_ms','rag_reformulation_ms','llm_open_ms','llm_first_token_ms',
'llm_total_ms','tts_first_sentence_ms','tts_total_ms','first_text_ms','first_audio_ms','actions_ms','total_ms',
'audio_original_bytes','audio_base64_bytes','llm_tokens','tts_sentences','pending_peak','tts_active_peak'}
class PerformanceTrace:
    def __init__(self): self.started=time.perf_counter();self.values={};self.operation=None
    def add(self,key,value):
        if key in FIELDS and isinstance(value,(int,float)) and math.isfinite(value):
            self.values[key]=self.values.get(key,0)+value
    def first(self,key,origin=None):
        if key not in self.values:self.values[key]=(time.perf_counter()-(origin or self.started))*1000
    def report(self):
        self.first('total_ms');token=request_id.set(self.operation or request_id.get())
        try:safe_event('pipeline_metrics',**{k:round(v,3) for k,v in self.values.items() if k in FIELDS and isinstance(v,(int,float)) and math.isfinite(v)})
        finally:request_id.reset(token)
def duration(key,started):
    trace=current_trace.get()
    if trace:trace.add(key,(time.perf_counter()-started)*1000)
