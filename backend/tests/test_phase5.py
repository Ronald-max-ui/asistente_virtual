"""Index safety, routing and real local Chroma/FastEmbed acceptance regression."""
import contextlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import types
import unittest
import uuid
from contextlib import closing
from importlib.metadata import version
from pathlib import Path
from unittest.mock import patch
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from knowledge_config import BASE, IndexSettings, MODEL, COLLECTION
from services.knowledge_index import (KNOWLEDGE, SOURCES, CHUNKING, sha256, source_hashes,
    load_chunks, validate_sources, active_generation, check_generation, index_status,
    promote, rebuild, write_atomic, build_lock, KnowledgeIndex, IndexErrorControlled)
from services.knowledge_retrieval import retrieve, detectar_entidad
from services.health_service import readiness
from test_support import repository

@contextlib.contextmanager
def sql(path):
    with closing(sqlite3.connect(path)) as db:
        with db:
            yield db

def fake_generation(options, sources=KNOWLEDGE, text='Contenido académico de Administración.'):
    path=options.root/'generations'/('gen-'+uuid.uuid4().hex)
    path.mkdir(parents=True)
    digest=sha256(text.encode())
    metadata=dict(source_id='administracion',id='administracion',program_id='administracion',
        tipo='carrera_tecnica',categoria='02_carreras',titulo='Administración',heading='Descripción',
        fuente='02_carreras/administracion.md',content_sha256=digest)
    with sql(path/'chroma.sqlite3') as db:
        db.executescript('CREATE TABLE collections(id TEXT,name TEXT,dimension INTEGER);'
            'CREATE TABLE embeddings(id INTEGER);'
            'CREATE TABLE embedding_metadata(id INTEGER,key TEXT,string_value TEXT);'
            'CREATE TABLE embeddings_queue(seq_id INTEGER,id TEXT,vector BLOB,encoding TEXT);')
        db.execute('INSERT INTO collections VALUES(?,?,?)',('one',COLLECTION,384))
        db.execute('INSERT INTO embeddings VALUES(1)')
        for key,value in {**metadata,'chroma:document':text}.items():
            db.execute('INSERT INTO embedding_metadata VALUES(?,?,?)',(1,key,value))
    (path/'vectors').mkdir()
    (path/'vectors/header.bin').write_bytes(b'vector-fixture')
    np.savez_compressed(path/'embedding_integrity.npz',ids=np.asarray(['fixture']),vectors=np.zeros((1,384),dtype='<f4'))
    hashes=source_hashes(sources)
    manifest=dict(schema_version=1,generated_at='2026-10-07T00:00:00+00:00',embedding_model=MODEL,
        embedding_dimension=384,chunking_version=CHUNKING,collection_name=COLLECTION,
        chunk_count=1,distance_metric='cosine',source_files=list(SOURCES),source_hashes=hashes,
        chunks_sha256=sha256(digest.encode()),model_artifacts={'model.onnx':'fixture'},
        index_files={'vectors/header.bin':{'size':14,'sha256':sha256(b'vector-fixture')}},
        queue_sha256=sha256(b''),
        embedding_integrity_sha256=sha256((path/'embedding_integrity.npz').read_bytes()),
        versions={name:version(name) for name in ('fastembed','chromadb')},evaluation={'passed':True})
    write_atomic(path/'manifest.json',manifest)
    return path,manifest

class IndexSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name)
        self.options=IndexSettings(self.directory/'index')

    def active(self,sources=KNOWLEDGE):
        path,manifest=fake_generation(self.options,sources)
        promote(path,self.options,sources)
        return path,manifest

    def test_path_is_backend_relative_and_independent_of_cwd(self):
        initial=Path.cwd()
        try:
            with patch.dict(os.environ,{'CHROMA_DB_PATH':'storage/knowledge_index','CHROMA_COLLECTION_NAME':COLLECTION}):
                for directory in (BASE.parent,BASE,self.directory):
                    os.chdir(directory)
                    options=IndexSettings.from_env()
                    self.assertEqual(options.root,BASE/'storage/knowledge_index')
                    self.assertEqual(options.collection,COLLECTION)
        finally: os.chdir(initial)
        for kwargs in ({'model':'unknown'},{'dimension':768},{'collection':'knowledge'},{'top_k':200},{'max_distance':3}):
            with self.assertRaises(ValueError): IndexSettings(self.options.root,**kwargs)

    def test_missing_index_has_no_legacy_fallback_or_automatic_creation(self):
        self.assertEqual(index_status(self.options),{'status':'invalid'})
        self.assertFalse(self.options.root.exists())
        with self.assertRaises(IndexErrorControlled): KnowledgeIndex(self.options).search('Gastronomía')
        self.assertFalse(self.options.root.exists())

    def test_only_explicit_sources_indexed_and_chunks_have_context(self):
        sources=self.directory/'knowledge'
        shutil.copytree(KNOWLEDGE,sources)
        (self.directory/'fase-4-fuentes-originales.md').write_text('Histórico: S/ 999',encoding='utf-8')
        (sources/'temporary.pricing.json').write_text('{"amount":999}',encoding='utf-8')
        with contextlib.redirect_stdout(io.StringIO()): chunks,hashes=load_chunks(sources)
        self.assertEqual(set(hashes),set(SOURCES))
        self.assertEqual({doc.metadata['fuente'] for doc in chunks},set(SOURCES))
        for doc in chunks:
            self.assertLessEqual(len(doc.page_content),800)
            self.assertTrue({'source_id','tipo','categoria','titulo','heading'}<=doc.metadata.keys())
            if doc.metadata['tipo'] in ('carrera_tecnica','curso_corto'):
                self.assertEqual(doc.metadata['program_id'],doc.metadata['source_id'])
        (sources/'historical.md').write_text('Histórico',encoding='utf-8')
        with self.assertRaises(IndexErrorControlled): validate_sources(sources)

    def test_invalid_markdown_aborts_before_build_or_replacement(self):
        path,_=self.active()
        before=(self.options.root/'active.json').read_bytes()
        sources=self.directory/'knowledge'; shutil.copytree(KNOWLEDGE,sources)
        (sources/SOURCES[0]).write_bytes(b'\xff')
        with patch('services.knowledge_index.subprocess.run') as run:
            with self.assertRaises(IndexErrorControlled): rebuild(self.options,sources)
            run.assert_not_called()
        self.assertEqual(before,(self.options.root/'active.json').read_bytes())
        self.assertEqual(active_generation(self.options),path)

    def test_failed_temporary_build_keeps_active_index(self):
        path,_=self.active()
        before=(self.options.root/'active.json').read_bytes()
        def failing(command,**kwargs):
            candidate=Path(command[command.index('--worker')+1])
            self.assertNotEqual(candidate,path)
            self.assertEqual(active_generation(self.options),path)
            self.assertTrue(candidate.is_dir())
            return types.SimpleNamespace(returncode=1)
        with self.assertRaises(IndexErrorControlled): rebuild(self.options,runner=failing)
        self.assertEqual((self.options.root/'active.json').read_bytes(),before)
        self.assertEqual(index_status(self.options)['status'],'ready')
        self.assertFalse((self.options.root/'rebuild.lock').exists())

    def test_failed_worker_validation_and_timeout_keep_selector(self):
        self.active(); before=(self.options.root/'active.json').read_bytes()
        with self.assertRaises((IndexErrorControlled,OSError)):
            rebuild(self.options,runner=lambda *a,**k:types.SimpleNamespace(returncode=0))
        self.assertEqual((self.options.root/'active.json').read_bytes(),before)
        with self.assertRaises(subprocess.TimeoutExpired):
            rebuild(self.options,runner=lambda *a,**k:(_ for _ in ()).throw(subprocess.TimeoutExpired('worker',600)))
        self.assertEqual((self.options.root/'active.json').read_bytes(),before)

    def test_build_lock_prevents_simultaneous_promotion(self):
        with build_lock(self.options.root):
            with self.assertRaises(IndexErrorControlled):
                with build_lock(self.options.root): pass
        self.assertFalse((self.options.root/'rebuild.lock').exists())

    def test_atomic_promotion_retains_previous_generation(self):
        old,_=self.active()
        new,manifest=fake_generation(self.options)
        promote(new,self.options)
        self.assertEqual(active_generation(self.options),new)
        self.assertTrue(old.is_dir())
        self.assertEqual(check_generation(old,self.options)[0]['status'],'ready')
        self.assertFalse(list(self.options.root.glob('*.tmp-*')))

    def test_hash_change_marks_stale_and_prevents_promotion(self):
        sources=self.directory/'knowledge'; shutil.copytree(KNOWLEDGE,sources)
        path,manifest=self.active(sources)
        with (sources/SOURCES[0]).open('a',encoding='utf-8') as file: file.write('\nInformación académica nueva.\n')
        self.assertEqual(index_status(self.options,sources),{'status':'stale'})
        with self.assertRaises(IndexErrorControlled): promote(path,self.options,sources)
        self.assertEqual(set(manifest['source_hashes']),set(SOURCES))

    def test_new_markdown_source_marks_stale_until_explicitly_registered(self):
        sources=self.directory/'knowledge'; shutil.copytree(KNOWLEDGE,sources)
        self.active(sources)
        (sources/'new.md').write_text('# Nueva ficha\nContenido académico.',encoding='utf-8')
        self.assertEqual(index_status(self.options,sources),{'status':'stale'})
        with self.assertRaises(IndexErrorControlled): rebuild(self.options,sources)

    def test_empty_corrupt_incompatible_and_multiple_collections_rejected(self):
        for condition in ('empty','sqlite','manifest','dimension','collection','two_collections','model','vector'):
            path,manifest=fake_generation(self.options)
            if condition=='empty':
                with sql(path/'chroma.sqlite3') as db: db.execute('DELETE FROM embeddings')
            elif condition=='sqlite': (path/'chroma.sqlite3').write_bytes(b'corrupt database')
            elif condition=='manifest': (path/'manifest.json').write_text('{broken',encoding='utf-8')
            elif condition=='dimension':
                manifest['embedding_dimension']=768; write_atomic(path/'manifest.json',manifest)
            elif condition=='model':
                manifest['embedding_model']='unknown'; write_atomic(path/'manifest.json',manifest)
            elif condition=='vector': (path/'vectors/header.bin').write_bytes(b'corrupt vector')
            else:
                with sql(path/'chroma.sqlite3') as db:
                    if condition=='collection': db.execute("UPDATE collections SET name='knowledge'")
                    else: db.execute("INSERT INTO collections VALUES('two','other',384)")
            self.assertEqual(check_generation(path,self.options)[0],{'status':'invalid'},condition)
            with self.assertRaises(IndexErrorControlled): promote(path,self.options)

    def test_chunk_content_and_metadata_corruption_are_detected(self):
        for statement in ("UPDATE embedding_metadata SET string_value='changed' WHERE key='chroma:document'",
                    "DELETE FROM embedding_metadata WHERE key='program_id'"):
            path,_=fake_generation(self.options)
            with sql(path/'chroma.sqlite3') as db: db.execute(statement)
            self.assertEqual(check_generation(path,self.options)[0]['status'],'invalid')

    def test_selector_cannot_traverse_to_another_directory(self):
        self.options.root.mkdir()
        write_atomic(self.options.root/'active.json',{'schema_version':1,'generation':'../../chroma_db'})
        self.assertEqual(index_status(self.options),{'status':'invalid'})

    def test_health_exposes_only_safe_index_state(self):
        for state in ('ready','stale','invalid'):
            with patch('services.health_service.index_status',return_value={'status':state}):
                result=readiness(repository)
            self.assertEqual(result['knowledge'],{'status':state})
            self.assertEqual(result['checks']['knowledge'],state!='invalid')
            if state=='invalid': self.assertEqual(result['status'],'not_ready')
            self.assertNotIn('source_hashes',json.dumps(result))
            self.assertNotIn(str(BASE),json.dumps(result))

class RetrievalTests(unittest.TestCase):
    def test_single_query_embedding_and_known_metadata_filter(self):
        options=IndexSettings(Path('storage/knowledge_index'))
        class Embeddings:
            calls=0
            def query_embed(self,text):
                self.calls+=1
                yield np.zeros(384)
        class Collection:
            def query(self,**kwargs):
                self.kwargs=kwargs
                return {'documents':[['Relevant','Relevant','Distant']],
                    'metadatas':[[{'source_id':'gastronomia'}]*3],'distances':[[0.2,0.3,0.9]]}
        embedder,collection=Embeddings(),Collection()
        docs=retrieve(collection,embedder,'Gastronomía es virtual',options,'gastronomia')
        self.assertEqual(embedder.calls,1)
        self.assertEqual(collection.kwargs['where'],{'program_id':'gastronomia'})
        self.assertEqual(len(docs),1)
        self.assertEqual(collection.kwargs['n_results'],6)
        self.assertEqual(detectar_entidad('¿Japonés se enseña en Administración?'),'administracion')
        self.assertEqual(detectar_entidad('¿Qué idiomas japonés enseña?'),'turismo')

    def test_general_question_ignores_unrelated_history_programme(self):
        options=IndexSettings(Path('storage/knowledge_index'))
        embedder=types.SimpleNamespace(query_embed=lambda text:iter([np.zeros(384)]))
        class Collection:
            def query(self,**kwargs):
                self.where=kwargs['where']
                return {'documents':[[]],'metadatas':[[]],'distances':[[]]}
        collection=Collection()
        retrieve(collection,embedder,'¿Dónde queda el instituto?',options,'gastronomia')
        self.assertEqual(collection.where,{'source_id':'institucional_general'})

    def test_related_institutional_search_reuses_exact_query_vector(self):
        options=IndexSettings(Path('storage/knowledge_index'))
        class Embeddings:
            calls=0
            def query_embed(self,text):
                self.calls+=1
                yield np.zeros(384)
        class Collection:
            calls=[]
            def query(self,**kwargs):
                self.calls.append(kwargs)
                return {'documents':[[]],'metadatas':[[]],'distances':[[]]}
        embedder,collection=Embeddings(),Collection()
        retrieve(collection,embedder,'Documentos necesarios para Gastronomía',options,'gastronomia')
        self.assertEqual(embedder.calls,1)
        self.assertEqual(len(collection.calls),2)
        self.assertEqual(collection.calls[0]['where'],{'program_id':'gastronomia'})
        self.assertEqual(collection.calls[1]['where'],{'source_id':'admision_y_pagos'})
        self.assertIs(collection.calls[0]['query_embeddings'][0],collection.calls[1]['query_embeddings'][0])

    def test_incompatible_query_dimension_is_rejected(self):
        options=IndexSettings(Path('storage/knowledge_index'))
        embedder=types.SimpleNamespace(query_embed=lambda text:iter([np.zeros(768)]))
        with self.assertRaises(ValueError): retrieve(None,embedder,'Gastronomía',options)

    def test_runtime_does_not_mix_generations_when_selector_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            options=IndexSettings(Path(directory)/'index')
            old,_=fake_generation(options); promote(old,options)
            new,_=fake_generation(options)
            index=KnowledgeIndex(options)
            collection=object()
            def search(c,e,q,o,entity):
                self.assertIs(c,collection)
                promote(new,options)
                return ['old query completed coherently']
            with patch('services.knowledge_index.create_embedder',return_value=object()), \
                 patch('services.knowledge_index.model_artifacts',return_value={'model.onnx':'fixture'}), \
                 patch('services.knowledge_index.open_collection',return_value=collection), \
                 patch('services.knowledge_index.verify_collection_vectors'), \
                 patch('services.knowledge_retrieval.retrieve',side_effect=search):
                self.assertEqual(index.search('Gastronomía'),['old query completed coherently'])
                self.assertEqual(index._current[0],old)
                self.assertEqual(active_generation(options),new)

    def test_stale_draft_does_not_disable_previously_validated_active_index(self):
        with tempfile.TemporaryDirectory() as directory:
            options=IndexSettings(Path(directory)/'index')
            path,manifest=fake_generation(options); promote(path,options)
            manifest['source_hashes'][SOURCES[0]]='0'*64
            write_atomic(path/'manifest.json',manifest)
            self.assertEqual(index_status(options),{'status':'stale'})
            with patch('services.knowledge_index.create_embedder',return_value=object()), \
                 patch('services.knowledge_index.model_artifacts',return_value={'model.onnx':'fixture'}), \
                 patch('services.knowledge_index.open_collection',return_value=object()), \
                 patch('services.knowledge_index.verify_collection_vectors'), \
                 patch('services.knowledge_retrieval.retrieve',return_value=['validated active context']):
                self.assertEqual(KnowledgeIndex(options).search('Gastronomía'),['validated active context'])
            with self.assertRaises(IndexErrorControlled): promote(path,options)

class RealIndexTests(unittest.TestCase):
    def test_real_offline_build_manifest_health_and_acceptance_queries(self):
        # Separate worker/evaluator processes close native Windows handles before
        # cleanup. No Groq/TTS calls or external model downloads are permitted.
        with tempfile.TemporaryDirectory() as directory:
            options=IndexSettings(Path(directory)/'index')
            manifest=rebuild(options)
            self.assertTrue(manifest['evaluation']['passed'])
            self.assertEqual(len(manifest['evaluation']['cases']),12)
            self.assertGreater(manifest['chunk_count'],0)
            self.assertEqual(manifest['embedding_dimension'],384)
            self.assertTrue(manifest['model_artifacts'])
            self.assertTrue(manifest['index_files'])
            self.assertEqual(index_status(options),{'status':'ready'})
            env={**os.environ,'CHROMA_DB_PATH':str(options.root),'CHROMA_LOCAL_FILES_ONLY':'true',
                 'PYTHONIOENCODING':'utf-8'}
            result=subprocess.run([sys.executable,'-B',str(BASE/'rebuild_knowledge.py'),'--evaluate'],
                env=env,capture_output=True,text=True,encoding='utf-8',timeout=180)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            evaluation=json.loads(result.stdout)
            self.assertTrue(evaluation['passed'])
            self.assertEqual(index_status(options),{'status':'ready'})

if __name__=='__main__': unittest.main()
