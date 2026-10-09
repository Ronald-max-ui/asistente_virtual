"""Immutable Chroma generations, validated manifests and atomic active selector.

No index creation occurs at import/startup. Optional startup warmup reuses the
validated generation without regeneration or external providers. Old and
failed generations are retained; runtime never searches legacy directories.
"""
import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import threading
import uuid
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from knowledge_config import IndexSettings, BASE
from persistence.chroma_integrity import inspect_database, persisted_queue_digest, queue_digest
from validate_knowledge import validate_knowledge

SOURCES = (
    '01_institucional/general.md','01_institucional/admision_y_pagos.md',
    '02_carreras/administracion.md','02_carreras/contabilidad.md',
    '02_carreras/gastronomia.md','02_carreras/turismo.md',
    '03_cursos_cortos/bartender.md','03_cursos_cortos/panaderia_pasteleria.md',
    '04_faqs/preguntas_frecuentes.md',
)
KNOWLEDGE = BASE / 'knowledge'
CHUNKING = 'markdown-headings-800-overlap80-merged-h3-title-v4'
REQUIRED_META = {'source_id','tipo','categoria','titulo','heading','fuente','content_sha256'}

class IndexErrorControlled(ValueError):
    pass

def sha256(data):
    return hashlib.sha256(data).hexdigest()

def vectors_digest(ids, vectors):
    import numpy as np
    return sha256(b''.join(identifier.encode()+b'\0'+np.asarray(vector,dtype='<f4').tobytes()
                          for identifier,vector in sorted(zip(ids,vectors))))



def source_hashes(root=KNOWLEDGE):
    root=Path(root).resolve()
    result={}
    for name in SOURCES:
        path=(root/name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise IndexErrorControlled('Missing knowledge source')
        result[name]=sha256(path.read_bytes())
    return result

def validate_sources(root=KNOWLEDGE):
    report=validate_knowledge(root)
    if report.errors or set(report.files)!=set(SOURCES):
        raise IndexErrorControlled('Knowledge validation failed; review validate_knowledge.py')
    return report

def load_chunks(root=KNOWLEDGE):
    from ingest import cargar_archivos_md
    validate_sources(root)
    before=source_hashes(root)
    chunks=cargar_archivos_md(str(root))
    if not chunks or before!=source_hashes(root):
        raise IndexErrorControlled('Knowledge changed during chunking')
    merged=[]
    for doc in chunks:
        previous=merged[-1] if merged else None
        if (previous and previous.metadata['fuente']==doc.metadata['fuente'] and
            previous.metadata.get('h2')==doc.metadata.get('h2') and
            (previous.metadata.get('h3') or doc.metadata.get('h3')) and
            len(previous.page_content)+len(doc.page_content)+2<=800):
            previous.page_content+='\n\n'+doc.page_content
            sections=[previous.metadata.get('h3',''),doc.metadata.get('h3','')]
            previous.metadata['h3']=' / '.join(dict.fromkeys(section for section in sections if section))
        else: merged.append(doc)
    chunks=merged
    for doc in chunks:
        meta=doc.metadata
        meta['source_id']=meta['id']
        if meta['tipo'] in ('carrera_tecnica','curso_corto'):
            meta['program_id']=meta['id']
        meta['heading']=' > '.join(meta[key] for key in ('h1','h2','h3') if key in meta)
        meta['content_sha256']=sha256(doc.page_content.encode('utf-8'))
        if not REQUIRED_META<=meta.keys() or len(doc.page_content)>800:
            raise IndexErrorControlled('Invalid chunk')
    return chunks,before

def write_atomic(path, data):
    path=Path(path)
    temporary=path.with_name(path.name+'.tmp-'+uuid.uuid4().hex)
    try:
        with temporary.open('x',encoding='utf-8',newline='\n') as file:
            json.dump(data,file,ensure_ascii=False,indent=2)
            file.write('\n')
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)

def active_generation(options):
    try:
        pointer=json.loads((options.root/'active.json').read_text(encoding='utf-8'))
        name=pointer['generation']
        if pointer['schema_version']!=1 or not re.fullmatch(r'gen-[a-f0-9]{32}',name):
            raise ValueError('Invalid selector')
        path=(options.root/'generations'/name).resolve()
        if not path.is_relative_to(options.root/'generations') or not path.is_dir():
            raise ValueError('Missing generation')
        return path
    except (OSError,ValueError,KeyError,TypeError) as exc:
        raise IndexErrorControlled('Knowledge index unavailable') from exc

def check_generation(path, options, source_root=KNOWLEDGE):
    """Read-only integrity check: never creates an empty Chroma database."""
    try:
        manifest=json.loads((path/'manifest.json').read_text(encoding='utf-8'))
        if (manifest['schema_version']!=1 or manifest['collection_name']!=options.collection or
            manifest['embedding_model']!=options.model or manifest['embedding_dimension']!=options.dimension or
            manifest['chunking_version']!=CHUNKING or manifest['distance_metric']!='cosine' or
            manifest['versions']['fastembed']!=version('fastembed') or
            manifest['versions']['chromadb']!=version('chromadb') or
            set(manifest['source_files'])!=set(SOURCES) or set(manifest['source_hashes'])!=set(SOURCES) or
            not manifest['model_artifacts'] or not manifest['evaluation']['passed']):
            raise ValueError('Incompatible manifest')
        if not isinstance(manifest['chunk_count'],int) or manifest['chunk_count']<=0:
            raise ValueError('Empty index')
        if sha256((path/'embedding_integrity.npz').read_bytes())!=manifest['embedding_integrity_sha256']:
            raise ValueError('Canonical vectors corrupt')
        files=manifest['index_files']
        actual={p.relative_to(path).as_posix() for p in path.rglob('*.bin') if p.is_file()}
        if not files or set(files)!=actual: raise ValueError('Vector files missing')
        for name,details in files.items():
            file=(path/name).resolve()
            if (not file.is_relative_to(path.resolve()) or file.stat().st_size!=details['size'] or
                ('sha256' in details and sha256(file.read_bytes())!=details['sha256'])):
                raise ValueError('Vector file corrupt')
        inspect_database(path, manifest, options, REQUIRED_META, SOURCES)
        try:
            current_files={p.relative_to(source_root).as_posix() for p in Path(source_root).rglob('*.md')}
            status='ready' if source_hashes(source_root)==manifest['source_hashes'] and current_files==set(SOURCES) else 'stale'
        except (OSError,ValueError):
            # An invalid/missing draft source must not disable a previously
            # validated active index. Its persisted integrity is still checked.
            status='stale'
        return {'status':status},manifest
    except (OSError,ValueError,KeyError,TypeError,sqlite3.Error):
        return {'status':'invalid'},None

def index_status(options=None, source_root=KNOWLEDGE, *, verify_vectors=False):
    try:
        options=options or IndexSettings.from_env()
        path=active_generation(options)
        result,manifest=check_generation(path,options,source_root)
        if verify_vectors and result['status'] in ('ready','stale'):
            verify_collection_vectors(open_collection(path,options),manifest,options,path)
        return result
    except Exception:
        return {'status':'invalid'}

def model_artifacts(embedder):
    # Version-pinned FastEmbed exposes this model directory. Record file hashes,
    # not local paths; compatibility is checked before any runtime query.
    root=Path(embedder.model._model_dir)
    files=sorted(path for path in root.rglob('*') if path.is_file() and path.suffix in ('.onnx','.json'))
    result={path.relative_to(root).as_posix():sha256(path.read_bytes()) for path in files}
    if not any(name.endswith('.onnx') for name in result): raise IndexErrorControlled('Model artifact missing')
    return result

def create_embedder(options):
    from fastembed import TextEmbedding
    return TextEmbedding(model_name=options.model,threads=options.threads,cache_dir=options.cache_dir,
                         local_files_only=options.local_files_only)

def open_collection(path, options):
    import chromadb
    from chromadb.config import Settings
    # get_collection deliberately does not create a missing collection.
    client=chromadb.PersistentClient(path=str(path),settings=Settings(anonymized_telemetry=False))
    return client.get_collection(options.collection,embedding_function=None)

@contextmanager
def build_lock(root):
    root.mkdir(parents=True,exist_ok=True)
    path=root/'rebuild.lock'
    try: descriptor=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError as exc: raise IndexErrorControlled('Another rebuild is active; inspect rebuild.lock') from exc
    try:
        with os.fdopen(descriptor,'w') as file: file.write(str(os.getpid()))
        yield
    finally: path.unlink(missing_ok=True)

def promote(path, options, source_root=KNOWLEDGE):
    status,manifest=check_generation(path,options,source_root)
    if status['status']!='ready': raise IndexErrorControlled('Candidate index is not ready')
    if path.parent.resolve()!=(options.root/'generations').resolve():
        raise IndexErrorControlled('Candidate outside generation root')
    write_atomic(options.root/'active.json',{'schema_version':1,'generation':path.name})
    return manifest

def seal_generation(path):
    # The worker has exited: native Chroma handles have flushed and closed.
    manifest=json.loads((path/'manifest.json').read_text(encoding='utf-8'))
    # Native HNSW buffers include unused allocated slots that can change upon
    # reopening even without writes. Hashing their entire allocation is invalid.
    # Check structural sizes/header; validate canonical vectors independently.
    manifest['index_files']={p.relative_to(path).as_posix():{
        'size':p.stat().st_size,**({'sha256':sha256(p.read_bytes())} if p.name=='header.bin' else {})}
        for p in sorted(path.rglob('*.bin')) if p.is_file()}
    if not manifest['index_files']: raise IndexErrorControlled('Missing vector artifacts')
    manifest['queue_sha256']=persisted_queue_digest(path)
    write_atomic(path/'manifest.json',manifest)

def rebuild(options=None, source_root=KNOWLEDGE, runner=None):
    options=options or IndexSettings.from_env()
    validate_sources(source_root)  # Must happen before any index mutation.
    with build_lock(options.root):
        candidate=options.root/'generations'/('gen-'+uuid.uuid4().hex)
        candidate.mkdir(parents=True)
        # Separate process closes Windows SQLite/HNSW handles before promotion.
        command=[sys.executable,'-B',str(BASE/'rebuild_knowledge.py'),'--worker',str(candidate),
            '--source-root',str(Path(source_root).resolve()),'--options',json.dumps({
                **options.__dict__,'root':str(options.root)})]
        outcome=(runner or subprocess.run)(command,timeout=600,check=False)
        if outcome.returncode!=0: raise IndexErrorControlled('Candidate build failed; previous selector unchanged')
        verify_command=command.copy()
        verify_command[verify_command.index('--worker')]='--verify'
        outcome=(runner or subprocess.run)(verify_command,timeout=180,check=False)
        if outcome.returncode!=0: raise IndexErrorControlled('Persisted candidate validation failed')
        seal_generation(candidate)
        return promote(candidate,options,source_root)

def build_worker(candidate, options, source_root=KNOWLEDGE):
    import chromadb
    from chromadb.config import Settings
    from services.knowledge_evaluation import evaluate
    chunks,hashes=load_chunks(source_root)
    embedder=create_embedder(options)
    # Short sections need the programme identity during embedding too, not only
    # as a metadata filter or a prefix added after retrieval.
    inputs=[f"{doc.metadata['titulo']} | {doc.metadata['heading']}\n{doc.page_content}" for doc in chunks]
    vectors=[vector.tolist() for vector in embedder.embed(inputs,batch_size=16)]
    if len(vectors)!=len(chunks) or any(len(v)!=options.dimension or not all(math.isfinite(x) for x in v) for v in vectors):
        raise IndexErrorControlled('Invalid document embeddings')
    client=chromadb.PersistentClient(path=str(candidate),settings=Settings(anonymized_telemetry=False))
    collection=client.create_collection(options.collection,embedding_function=None,
        configuration={'hnsw':{'space':'cosine'}},metadata={'schema_version':1,'embedding_model':options.model,'chunking_version':CHUNKING})
    identifiers=[sha256((doc.metadata['fuente']+'\n'+str(i)+'\n'+doc.page_content).encode()) for i,doc in enumerate(chunks)]
    collection.add(ids=identifiers,documents=[doc.page_content for doc in chunks],
        metadatas=[doc.metadata for doc in chunks],embeddings=vectors)
    import numpy as np
    np.savez_compressed(candidate/'embedding_integrity.npz',ids=np.asarray(identifiers),vectors=np.asarray(vectors,dtype='<f4'))
    evaluation=evaluate(collection,embedder,options)
    write_atomic(candidate/'evaluation.json',evaluation)
    if not evaluation['passed']: raise IndexErrorControlled('Retrieval evaluation failed')
    if hashes!=source_hashes(source_root): raise IndexErrorControlled('Sources changed during build')
    manifest=dict(schema_version=1,generated_at=datetime.now(timezone.utc).isoformat(),
        embedding_model=options.model,embedding_dimension=options.dimension,chunking_version=CHUNKING,
        chunk_size=800,chunk_overlap=80,source_files=list(SOURCES),source_hashes=hashes,
        chunk_count=len(chunks),collection_name=options.collection,distance_metric='cosine',
        chunks_sha256=sha256('\n'.join(sorted(doc.metadata['content_sha256'] for doc in chunks)).encode()),
        vectors_sha256=vectors_digest(identifiers,vectors),
        embedding_integrity_sha256=sha256((candidate/'embedding_integrity.npz').read_bytes()),
        model_artifacts=model_artifacts(embedder),versions={p:version(p) for p in ('fastembed','chromadb','onnxruntime','numpy','langchain-text-splitters')},
        retrieval=dict(top_k=options.top_k,max_context_chunks=options.max_context_chunks,max_distance=options.max_distance),
        evaluation=evaluation)
    write_atomic(candidate/'manifest.json',manifest)
    return manifest

def verify_collection_vectors(collection, manifest, options, path):
    import numpy as np
    result=collection.get(include=['embeddings'])
    vectors=result['embeddings']
    with np.load(path/'embedding_integrity.npz',allow_pickle=False) as data:
        expected={str(identifier):vector for identifier,vector in zip(data['ids'],data['vectors'])}
        if vectors_digest(data['ids'],data['vectors'])!=manifest['vectors_sha256']:
            raise IndexErrorControlled('Canonical vector digest incompatible')
    if (len(result['ids'])!=manifest['chunk_count'] or vectors is None or
        set(result['ids'])!=set(expected) or
        any(len(v)!=options.dimension or not all(math.isfinite(float(x)) for x in v) for v in vectors) or
        any(not np.allclose(v,expected[identifier],rtol=1e-5,atol=1e-6)
            for identifier,v in zip(result['ids'],vectors))):
        raise IndexErrorControlled('Persisted vectors incompatible')

def verify_persisted(path, options):
    from services.knowledge_evaluation import evaluate
    manifest=json.loads((path/'manifest.json').read_text(encoding='utf-8'))
    collection=open_collection(path,options)
    verify_collection_vectors(collection,manifest,options,path)
    embedder=create_embedder(options)
    if model_artifacts(embedder)!=manifest['model_artifacts']:
        raise IndexErrorControlled('Model artifacts incompatible')
    evaluation=evaluate(collection,embedder,options)
    if not evaluation['passed']: raise IndexErrorControlled('Persisted retrieval evaluation failed')
    manifest['evaluation']=evaluation
    write_atomic(path/'evaluation.json',evaluation)
    write_atomic(path/'manifest.json',manifest)

class KnowledgeIndex:
    """Each query captures one generation; promotion never mixes its chunks."""
    def __init__(self, options=None):
        self.options=options or IndexSettings.from_env()
        self._lock=threading.RLock()
        self._current=None
        self._embedder=None
        self._artifacts=None
        self._validation=None

    def _validated_manifest(self,path):
        # Private immutable generations: detect ordinary writes immediately;
        # full hashes/SQL checks repeat at most every two seconds. Readiness and
        # administrative --check still run uncached full verification.
        paths=[self.options.root/'active.json',*sorted(path.rglob('*')),*sorted(KNOWLEDGE.rglob('*.md'))]
        signature=tuple((str(p),p.stat().st_size,p.stat().st_mtime_ns,p.stat().st_ctime_ns) for p in paths if p.is_file())
        now=time.monotonic()
        if self._validation and self._validation[:2]==(path,signature) and now-self._validation[2]<2:
            return self._validation[3]
        status,manifest=check_generation(path,self.options)
        if status['status'] not in ('ready','stale'):raise IndexErrorControlled('Knowledge index is invalid')
        self._validation=(path,signature,now,manifest)
        return manifest

    def search(self, query, entity=None):
        from services.knowledge_retrieval import retrieve
        with self._lock:
            path=active_generation(self.options)
            manifest=self._validated_manifest(path)
            if self._embedder is None:
                self._embedder=create_embedder(self.options)
                self._artifacts=model_artifacts(self._embedder)
            if self._artifacts!=manifest['model_artifacts']:
                raise IndexErrorControlled('Embedding artifacts incompatible')
            if self._current is None or self._current[0]!=path:
                collection=open_collection(path,self.options)
                verify_collection_vectors(collection,manifest,self.options,path)
                self._current=(path,collection)
            collection=self._current[1]
        return retrieve(collection,self._embedder,query,self.options,entity)
